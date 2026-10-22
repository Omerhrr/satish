"""On-chain TK payments to the operator's own watch-only wallet.

Each purchase gets a fresh BIP84 (native SegWit) address derived from the
operator's account xpub. The server can derive and watch addresses but can
never spend: the operator's recovery phrase never touches it. Payments are
detected through an Esplora API (mempool.space) and credited exactly once:

  1. the address must have received >= the purchase amount with at least
     XP_ONCHAIN_MIN_CONF confirmations (0 = accept once in the mempool),
  2. a compare-and-set moves the intent pending|expired -> settled (only one
     caller can win), and
  3. the ledger credit is keyed ``purchase:{intent_id}`` (replays are no-ops).

Late payments to an expired request are still credited (the money arrived),
for up to ``ONCHAIN_LATE_WINDOW_DAYS``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from embit import bip32, script
from embit.networks import NETWORKS
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import PaymentIntent, User
from xp_core.services import ledger

log = get_logger(__name__)

REF_PREFIX = "onchain:"
ONCHAIN_LATE_WINDOW_DAYS = 7
DEFAULT_ESPLORA = {
    "mainnet": "https://mempool.space/api",
    "testnet": "https://mempool.space/testnet4/api",
}


class OnchainConfigError(RuntimeError):
    pass


def _net(name: str) -> dict[str, Any]:
    if name == "mainnet":
        return NETWORKS["main"]
    if name == "testnet":
        return NETWORKS["test"]
    raise OnchainConfigError(f"unknown network {name!r}")


def esplora_url(settings: Settings) -> str:
    return (settings.onchain_esplora_url or DEFAULT_ESPLORA[settings.onchain_network]).rstrip("/")


def derive_address(xpub: str, network: str, index: int) -> str:
    """Receive address m/.../0/index for a BIP84 account xpub (any version bytes)."""
    try:
        account = bip32.HDKey.from_base58(xpub.strip())
    except Exception as exc:
        raise OnchainConfigError("XP_ONCHAIN_XPUB is not a valid extended public key") from exc
    if account.is_private:
        raise OnchainConfigError("XP_ONCHAIN_XPUB must be a PUBLIC key, never a private one")
    return script.p2wpkh(account.derive([0, index])).address(_net(network))


def bip21(address: str, amount_sats: int, label: str = "TK credits") -> str:
    btc = f"{amount_sats / 1e8:.8f}".rstrip("0").rstrip(".")
    return f"bitcoin:{address}?amount={btc}&label={label.replace(' ', '%20')}"


def is_onchain(row: PaymentIntent) -> bool:
    return bool(row.provider_reference and row.provider_reference.startswith(REF_PREFIX))


def intent_address(row: PaymentIntent) -> str | None:
    return row.provider_reference[len(REF_PREFIX):] if is_onchain(row) else None


@dataclass(slots=True)
class PaymentCheck:
    address: str
    counted_sats: int = 0  # meets the confirmation policy
    seen_sats: int = 0  # anything seen, including unconfirmed
    txids: list[str] = field(default_factory=list)


async def check_address(
    client: httpx.AsyncClient, base: str, address: str, min_conf: int
) -> PaymentCheck:
    tip_resp = await client.get(f"{base}/blocks/tip/height")
    tip_resp.raise_for_status()
    tip = int(tip_resp.text)
    resp = await client.get(f"{base}/address/{address}/txs")
    resp.raise_for_status()
    out = PaymentCheck(address=address)
    for tx in resp.json():
        value = sum(o.get("value", 0) for o in tx.get("vout", []) if o.get("scriptpubkey_address") == address)
        if not value:
            continue
        st = tx.get("status", {})
        confs = (tip - st["block_height"] + 1) if st.get("confirmed") and st.get("block_height") else 0
        out.seen_sats += value
        out.txids.append(tx["txid"])
        if confs >= min_conf:
            out.counted_sats += value
    return out


async def create_intent(
    session: AsyncSession, *, user: User, settings: Settings, amount_sats: int
) -> PaymentIntent:
    if not settings.onchain_xpub:
        raise OnchainConfigError("on-chain payments need XP_ONCHAIN_XPUB")
    used = (
        await session.execute(
            select(func.count()).select_from(PaymentIntent).where(PaymentIntent.provider_reference.like(f"{REF_PREFIX}%"))
        )
    ).scalar_one()
    index = int(used)
    for _ in range(50):  # skip any index already taken (concurrent creates)
        address = derive_address(settings.onchain_xpub, settings.onchain_network, index)
        taken = (
            await session.execute(select(PaymentIntent.id).where(PaymentIntent.provider_reference == REF_PREFIX + address))
        ).scalar_one_or_none()
        if taken is None:
            break
        index += 1
    row = PaymentIntent(
        user_id=user.id,
        provider_reference=REF_PREFIX + address,
        amount_sats=amount_sats,
        xp_amount=amount_sats * settings.xp_per_sat,
        status="pending",
        direction="receive",
        bolt11=bip21(address, amount_sats),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.onchain_request_ttl_minutes),
        idempotency_key=f"receive:{REF_PREFIX}{address}",
    )
    session.add(row)
    await session.flush()
    log.info("onchain_request_created", intent_id=row.id, index=index, network=settings.onchain_network)
    return row


async def settle_if_paid(
    session: AsyncSession,
    row: PaymentIntent,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> PaymentCheck | None:
    """Check the chain and credit TK once if paid. Returns what was seen."""
    if not is_onchain(row) or row.status == "settled":
        return None
    address = intent_address(row)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        check = await check_address(client, esplora_url(settings), address, settings.onchain_min_conf)
    finally:
        if owns_client:
            await client.aclose()

    if check.counted_sats >= row.amount_sats:
        won = await session.execute(
            update(PaymentIntent)
            .where(PaymentIntent.id == row.id, PaymentIntent.status.in_(("pending", "expired")))
            .values(status="settled", settled_at=datetime.now(UTC))
        )
        if won.rowcount:
            await ledger.credit_purchase(session, user_id=row.user_id, amount=row.xp_amount, payment_intent_id=row.id)
            log.info(
                "onchain_payment_credited",
                intent_id=row.id,
                received=check.counted_sats,
                overpaid=check.counted_sats - row.amount_sats,
                txids=check.txids,
            )
        await session.commit()
        await session.refresh(row)
    elif row.status == "pending" and row.expires_at is not None and check.seen_sats == 0:
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) >= expires:
            row.status = "expired"
            await session.commit()
    return check


async def sweep(session: AsyncSession, settings: Settings) -> dict[str, int]:
    """Worker job: check every open on-chain request (incl. recently expired)."""
    since = datetime.now(UTC) - timedelta(days=ONCHAIN_LATE_WINDOW_DAYS)
    rows = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.provider_reference.like(f"{REF_PREFIX}%"),
                or_(PaymentIntent.status == "pending", PaymentIntent.status == "expired"),
                PaymentIntent.created_at >= since.replace(tzinfo=None),
            )
        )
    ).scalars().all()
    settled = errors = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for row in rows:
            try:
                await settle_if_paid(session, row, settings, client=client)
                settled += int(row.status == "settled")
            except Exception as exc:
                errors += 1
                log.warning("onchain_check_failed", intent_id=row.id, error=str(exc))
    return {"checked": len(rows), "settled": settled, "errors": errors}
