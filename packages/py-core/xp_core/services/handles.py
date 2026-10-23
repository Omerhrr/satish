"""@usernames and payment requests for on-device wallets.

The server never sees keys or the wallet's xpub. A user's phone uploads a
pool of its own receive addresses, each signed by the wallet's identity key
(ECDSA over sha256("xp-handle-v1|<network>|<address>")). The server checks
every signature on upload and hands out one unused address per payment, so
each payer gets a fresh address. Payers' phones re-verify the signature and
pin the identity key, so a compromised server can't swap in its own address.

Payment requests reuse the same pool: a shareable link shows the request and
an address; the chain is checked (Esplora) to mark it paid and notify.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from embit import ec
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import (
    HandleAddress,
    Notification,
    PaymentRequest,
    User,
    WalletHandle,
)
from xp_core.services.onchain import DEFAULT_ESPLORA, check_address

log = get_logger(__name__)

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")
RESERVED = {
    "admin", "administrator", "support", "help", "xp", "xpwallet", "wallet", "bitcoin", "btc",
    "btrust", "satoshi", "root", "system", "official", "team", "staff", "security", "mod",
    "moderator", "null", "undefined", "me", "pay", "request", "telegram", "whatsapp",
}
NAME_HOLD_DAYS = 30  # a released name can't be taken by someone else for this long
POOL_MAX_AVAILABLE = 100
UPLOAD_MAX = 50
ADDRESS_RE = {
    "mainnet": re.compile(r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$"),
    "testnet": re.compile(r"^(tb1[02-9ac-hj-np-z]{11,71}|[mn2][1-9A-HJ-NP-Za-km-z]{25,34})$"),
}
PUBKEY_RE = re.compile(r"^0[23][0-9a-f]{64}$")
REQUEST_CHECK_SECONDS = 20


class HandleError(ValueError):
    """User-facing problem (the message is shown as-is)."""


def normalize_username(raw: str) -> str:
    return raw.strip().lstrip("@").lower()


def username_problem(name: str) -> str:
    if not USERNAME_RE.match(name):
        return "Use 3-20 characters: lowercase letters, numbers and _."
    if name in RESERVED:
        return "That name is reserved. Try another."
    return ""


def _network(network: str) -> str:
    if network not in ADDRESS_RE:
        raise HandleError("Unknown network.")
    return network


def address_message(network: str, address: str) -> bytes:
    return hashlib.sha256(f"xp-handle-v1|{network}|{address}".encode()).digest()


LN_NETWORKS = ("mainnet", "regtest", "signet")
_SPARK = re.compile(r"^[a-z]{2,10}1[02-9ac-hj-np-z]{20,280}$")


def normalize_spark(address: str) -> str:
    """Spark addresses as wallets may hand them over: 'spark:' URI prefix, any case."""
    a = address.strip()
    if a.lower().startswith("spark:"):
        a = a[6:]
    return a.lower()


def spark_message(network: str, ln_network: str, address: str) -> bytes:
    """What the identity key signs to vouch for a Lightning (Spark) address."""
    return hashlib.sha256(f"xp-handle-ln-v1|{network}|{ln_network}|{address}".encode()).digest()


def verify_spark_signature(identity_pubkey: str, network: str, ln_network: str, address: str, signature_hex: str) -> bool:
    try:
        pub = ec.PublicKey.parse(bytes.fromhex(identity_pubkey))
        sig = ec.Signature.parse(bytes.fromhex(signature_hex))
        return bool(pub.verify(sig, spark_message(network, ln_network, address)))
    except Exception:
        return False


async def set_lightning(
    session: AsyncSession, user: User, *, network: str, identity_pubkey: str, ln_network: str, spark_address: str, signature: str
) -> WalletHandle:
    """Publish (or replace) the Lightning address for my @username."""
    handle = await my_handle(session, user, _network(network))
    if handle is None:
        raise HandleError("Pick a username for your wallet first.")
    if handle.identity_pubkey != identity_pubkey:
        raise HandleError("This wallet doesn't own that username. Open Satish with the wallet that claimed it.")
    if ln_network not in LN_NETWORKS:
        raise HandleError("Unknown Lightning network.")
    address = normalize_spark(spark_address)
    if not _SPARK.match(address):
        raise HandleError("That isn't a valid Lightning (Spark) address.")
    if not verify_spark_signature(identity_pubkey, handle.network, ln_network, address, signature):
        raise HandleError("The Lightning address signature didn't check out.")
    handle.spark_address = address
    handle.spark_signature = signature
    handle.spark_network = ln_network
    await session.flush()
    return handle


def verify_address_signature(identity_pubkey: str, network: str, address: str, signature_hex: str) -> bool:
    try:
        pub = ec.PublicKey.parse(bytes.fromhex(identity_pubkey))
        sig = ec.Signature.parse(bytes.fromhex(signature_hex))
        return bool(pub.verify(sig, address_message(network, address)))
    except Exception:
        return False


@dataclass(slots=True)
class SignedAddress:
    address: str
    index: int
    signature: str


# ------------------------------------------------------------------ handles


async def active_handle(session: AsyncSession, network: str, username: str) -> WalletHandle | None:
    return (
        await session.execute(
            select(WalletHandle).where(
                WalletHandle.network == network,
                WalletHandle.username == username,
                WalletHandle.status == "active",
            )
        )
    ).scalar_one_or_none()


async def my_handle(session: AsyncSession, user: User, network: str) -> WalletHandle | None:
    return (
        await session.execute(
            select(WalletHandle).where(
                WalletHandle.user_id == user.id,
                WalletHandle.network == network,
                WalletHandle.status == "active",
            )
        )
    ).scalar_one_or_none()


async def name_availability(session: AsyncSession, network: str, raw: str, user: User | None = None) -> str:
    """'' when the name can be claimed by ``user``, otherwise the reason."""
    name = normalize_username(raw)
    problem = username_problem(name)
    if problem:
        return problem
    row = (
        await session.execute(select(WalletHandle).where(WalletHandle.network == network, WalletHandle.username == name))
    ).scalar_one_or_none()
    if row is None or (user is not None and row.user_id == user.id):
        return ""
    if row.status == "active":
        return f"@{name} is taken."
    released = row.released_at.replace(tzinfo=UTC) if row.released_at and row.released_at.tzinfo is None else row.released_at
    if released and datetime.now(UTC) - released < timedelta(days=NAME_HOLD_DAYS):
        return f"@{name} was used recently and isn't available yet."
    return ""


async def add_addresses(
    session: AsyncSession, user: User, network: str, identity_pubkey: str, items: list[SignedAddress]
) -> int:
    """Verify and store signed pool addresses. Returns how many were added."""
    _network(network)
    if not PUBKEY_RE.match(identity_pubkey):
        raise HandleError("Invalid wallet key.")
    if len(items) > UPLOAD_MAX:
        raise HandleError(f"Upload at most {UPLOAD_MAX} addresses at a time.")
    available = (
        await session.execute(
            select(func.count()).select_from(HandleAddress).where(
                HandleAddress.user_id == user.id, HandleAddress.network == network, HandleAddress.status == "available"
            )
        )
    ).scalar_one()
    added = 0
    for item in items:
        if available + added >= POOL_MAX_AVAILABLE:
            break
        if not ADDRESS_RE[network].match(item.address) or item.index < 0:
            raise HandleError("One of the addresses isn't valid for this network.")
        if not verify_address_signature(identity_pubkey, network, item.address, item.signature):
            raise HandleError("An address signature didn't check out. Nothing was saved.")
        exists = (await session.execute(select(HandleAddress.id).where(HandleAddress.address == item.address))).scalar_one_or_none()
        if exists:
            continue
        session.add(
            HandleAddress(
                user_id=user.id,
                network=network,
                identity_pubkey=identity_pubkey,
                address=item.address,
                derivation_index=item.index,
                signature=item.signature,
            )
        )
        added += 1
    await session.flush()
    return added


async def claim(
    session: AsyncSession,
    user: User,
    *,
    network: str,
    username: str,
    identity_pubkey: str,
    addresses: list[SignedAddress],
) -> WalletHandle:
    """Claim or change @username for this user's wallet on ``network``."""
    _network(network)
    name = normalize_username(username)
    problem = await name_availability(session, network, name, user)
    if problem:
        raise HandleError(problem)
    if not PUBKEY_RE.match(identity_pubkey):
        raise HandleError("Invalid wallet key.")

    current = await my_handle(session, user, network)
    if current is not None and current.identity_pubkey != identity_pubkey:
        # a different wallet now: its old addresses must never be handed out again
        await session.execute(
            delete(HandleAddress).where(
                HandleAddress.user_id == user.id, HandleAddress.network == network, HandleAddress.status == "available"
            )
        )
    if current is not None and current.username != name:
        current.status = "released"
        current.released_at = datetime.now(UTC)

    row = (
        await session.execute(select(WalletHandle).where(WalletHandle.network == network, WalletHandle.username == name))
    ).scalar_one_or_none()
    if row is not None and row.user_id != user.id:
        await session.delete(row)  # someone else's long-released name
        await session.flush()
        row = None
    if row is None:
        row = WalletHandle(user_id=user.id, network=network, username=name, identity_pubkey=identity_pubkey)
        session.add(row)
    else:
        row.status = "active"
        row.released_at = None
        row.identity_pubkey = identity_pubkey
    await session.flush()
    await add_addresses(session, user, network, identity_pubkey, addresses)
    log.info("handle_claimed", user_id=user.id, network=network, username=name)
    return row


async def pool_status(session: AsyncSession, user: User, network: str) -> dict[str, int]:
    available = (
        await session.execute(
            select(func.count()).select_from(HandleAddress).where(
                HandleAddress.user_id == user.id, HandleAddress.network == network, HandleAddress.status == "available"
            )
        )
    ).scalar_one()
    max_index = (
        await session.execute(
            select(func.max(HandleAddress.derivation_index)).where(
                HandleAddress.user_id == user.id, HandleAddress.network == network
            )
        )
    ).scalar_one()
    issued_max = (
        await session.execute(
            select(func.max(HandleAddress.derivation_index)).where(
                HandleAddress.user_id == user.id, HandleAddress.network == network, HandleAddress.status == "issued"
            )
        )
    ).scalar_one()
    return {
        "available": int(available),
        "max_index": -1 if max_index is None else int(max_index),
        "issued_max_index": -1 if issued_max is None else int(issued_max),
    }


async def issue_address(session: AsyncSession, handle: WalletHandle) -> tuple[HandleAddress, bool]:
    """Next unused signed address for @handle. Returns (row, reused).

    When the pool is empty (the owner hasn't opened the app to top up), the
    most recently issued address is reused rather than failing the payment.
    """
    base = select(HandleAddress).where(
        HandleAddress.user_id == handle.user_id,
        HandleAddress.network == handle.network,
        HandleAddress.identity_pubkey == handle.identity_pubkey,
    )
    row = (
        await session.execute(base.where(HandleAddress.status == "available").order_by(HandleAddress.derivation_index).limit(1))
    ).scalar_one_or_none()
    if row is not None:
        row.status = "issued"
        row.issued_at = datetime.now(UTC)
        await session.flush()
        return row, False
    last = (
        await session.execute(base.where(HandleAddress.status == "issued").order_by(HandleAddress.issued_at.desc()).limit(1))
    ).scalar_one_or_none()
    if last is None:
        raise HandleError(f"@{handle.username} can't receive right now. Ask them to open their Satish wallet.")
    return last, True


# ------------------------------------------------------------------ payment requests


def new_request_id() -> str:
    return secrets.token_urlsafe(9)  # 12 url-safe chars


async def create_request(
    session: AsyncSession, user: User, *, network: str, amount_sats: int | None, note: str | None
) -> PaymentRequest:
    handle = await my_handle(session, user, _network(network))
    if handle is None:
        raise HandleError("Pick a username for your wallet first.")
    if amount_sats is not None and not (546 <= amount_sats <= 2_100_000_000_000_000):
        raise HandleError("Enter an amount of at least 546 sats.")
    addr, _ = await issue_address(session, handle)
    req = PaymentRequest(
        id=new_request_id(),
        user_id=user.id,
        network=network,
        username=handle.username,
        address=addr.address,
        signature=addr.signature,
        identity_pubkey=addr.identity_pubkey,
        amount_sats=amount_sats,
        note=(note or "").strip()[:140] or None,
    )
    session.add(req)
    await session.flush()
    return req


def esplora_for(settings: Settings, network: str) -> str:
    if settings.onchain_esplora_url and network == settings.onchain_network:
        return settings.onchain_esplora_url.rstrip("/")
    return DEFAULT_ESPLORA[network]


async def refresh_request(
    session: AsyncSession, req: PaymentRequest, settings: Settings, *, client: httpx.AsyncClient | None = None, force: bool = False
) -> PaymentRequest:
    """Check the chain for an open request; mark paid and notify the owner once."""
    if req.status != "open":
        return req
    now = datetime.now(UTC)
    checked = req.checked_at.replace(tzinfo=UTC) if req.checked_at and req.checked_at.tzinfo is None else req.checked_at
    if not force and checked and (now - checked).total_seconds() < REQUEST_CHECK_SECONDS:
        return req
    owns = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        check = await check_address(client, esplora_for(settings, req.network), req.address, settings.onchain_min_conf)
    finally:
        if owns:
            await client.aclose()
    req.checked_at = now
    req.paid_sats = check.seen_sats
    target = req.amount_sats or 1
    if check.counted_sats >= target:
        req.status = "paid"
        req.paid_at = now
        session.add(
            Notification(
                user_id=req.user_id,
                kind="request.paid",
                payload={"request_id": req.id, "amount_sats": check.counted_sats, "note": req.note, "username": req.username},
            )
        )
        log.info("payment_request_paid", request_id=req.id, sats=check.counted_sats)
    await session.commit()
    return req


async def sweep_requests(session: AsyncSession, settings: Settings) -> dict[str, int]:
    since = datetime.now(UTC) - timedelta(days=30)
    rows = (
        await session.execute(
            select(PaymentRequest).where(PaymentRequest.status == "open", PaymentRequest.created_at >= since.replace(tzinfo=None))
        )
    ).scalars().all()
    paid = errors = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for req in rows:
            try:
                await refresh_request(session, req, settings, client=client, force=True)
                paid += int(req.status == "paid")
            except Exception as exc:
                errors += 1
                log.warning("request_check_failed", request_id=req.id, error=str(exc))
    return {"checked": len(rows), "paid": paid, "errors": errors}
