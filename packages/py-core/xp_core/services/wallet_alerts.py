"""Telegram messages when a user's on-device wallet receives bitcoin.

Opt-in and watch-only. The phone shares the receive addresses it shows (never
keys or the account public key, so the server can't see the whole wallet);
@username pool addresses the server already handed out are watched too.
Each payment produces at most one "received" message and one "confirmed"
message. Payments to shareable payment-request addresses are skipped here
because those already get their own "request paid" message.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import (
    HandleAddress,
    Notification,
    PaymentRequest,
    User,
    WalletAlertSetting,
    WatchedAddress,
)
from xp_core.services.onchain import DEFAULT_ESPLORA

log = get_logger(__name__)

MAX_WATCHED = 300  # per user per network
MAX_PER_SWEEP = 600
POOL_LOOKBACK_DAYS = 180
SEEN_KEEP = 60
_PREFIX = {"mainnet": "bc1", "testnet": "tb1"}
_ADDR = re.compile(r"^(bc1|tb1)[02-9ac-hj-np-z]{20,90}$")


class AlertError(ValueError):
    """Something the user should be told in plain words."""


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def valid_address(address: str, network: str) -> bool:
    a = address.strip().lower()
    return bool(_ADDR.match(a)) and a.startswith(_PREFIX[network])


async def _setting(session: AsyncSession, user_id: str, network: str) -> WalletAlertSetting | None:
    return (
        await session.execute(
            select(WalletAlertSetting).where(WalletAlertSetting.user_id == user_id, WalletAlertSetting.network == network)
        )
    ).scalar_one_or_none()


async def status(session: AsyncSession, user: User, network: str) -> dict[str, Any]:
    row = await _setting(session, user.id, network)
    count = (
        await session.execute(
            select(func.count()).select_from(WatchedAddress).where(
                WatchedAddress.user_id == user.id, WatchedAddress.network == network
            )
        )
    ).scalar_one()
    return {"enabled": bool(row and row.enabled), "watched": int(count)}


async def add_addresses(session: AsyncSession, user: User, network: str, addresses: list[str]) -> int:
    """Start watching these receive addresses (if alerts are on). Returns how many are new."""
    row = await _setting(session, user.id, network)
    if not row or not row.enabled:
        return 0
    clean = []
    for a in addresses:
        a = a.strip().lower()
        if not valid_address(a, network):
            raise AlertError("That isn't a valid address for this network.")
        if a not in clean:
            clean.append(a)
    if not clean:
        return 0
    existing = set(
        (
            await session.execute(
                select(WatchedAddress.address).where(WatchedAddress.user_id == user.id, WatchedAddress.address.in_(clean))
            )
        ).scalars()
    )
    new = [a for a in clean if a not in existing]
    count = (await status(session, user, network))["watched"]
    if count + len(new) > MAX_WATCHED:
        # keep the newest: drop the oldest watched addresses to make room
        overflow = count + len(new) - MAX_WATCHED
        old_ids = (
            await session.execute(
                select(WatchedAddress.id)
                .where(WatchedAddress.user_id == user.id, WatchedAddress.network == network)
                .order_by(WatchedAddress.created_at)
                .limit(overflow)
            )
        ).scalars().all()
        if old_ids:
            await session.execute(delete(WatchedAddress).where(WatchedAddress.id.in_(old_ids)))
    for a in new:
        session.add(WatchedAddress(user_id=user.id, network=network, address=a, seen={}, baseline=False))
    await session.commit()
    return len(new)


async def set_enabled(session: AsyncSession, user: User, network: str, enabled: bool, addresses: list[str]) -> dict[str, Any]:
    row = await _setting(session, user.id, network)
    if row is None:
        row = WalletAlertSetting(user_id=user.id, network=network, enabled=enabled)
        session.add(row)
    row.enabled = enabled
    row.updated_at = _naive(datetime.now(UTC))
    if not enabled:
        # Turning alerts off forgets every watched address.
        await session.execute(
            delete(WatchedAddress).where(WatchedAddress.user_id == user.id, WatchedAddress.network == network)
        )
    await session.commit()
    if enabled and addresses:
        await add_addresses(session, user, network, addresses)
    return await status(session, user, network)


async def forget_user(session: AsyncSession, user_id: str) -> None:
    await session.execute(delete(WatchedAddress).where(WatchedAddress.user_id == user_id))
    await session.execute(delete(WalletAlertSetting).where(WalletAlertSetting.user_id == user_id))


def _esplora(settings: Settings, network: str) -> str:
    if settings.onchain_esplora_url and network == settings.onchain_network:
        return settings.onchain_esplora_url.rstrip("/")
    return DEFAULT_ESPLORA[network]


async def _ensure_pool_rows(session: AsyncSession, setting: WalletAlertSetting) -> None:
    """Watch @username addresses we handed out (except payment-request ones)."""
    since = _naive(datetime.now(UTC) - timedelta(days=POOL_LOOKBACK_DAYS))
    issued = (
        await session.execute(
            select(HandleAddress.address).where(
                HandleAddress.user_id == setting.user_id,
                HandleAddress.network == setting.network,
                HandleAddress.status == "issued",
                HandleAddress.issued_at >= since,
            )
        )
    ).scalars().all()
    if not issued:
        return
    have = set(
        (
            await session.execute(
                select(WatchedAddress.address).where(
                    WatchedAddress.user_id == setting.user_id, WatchedAddress.address.in_(issued)
                )
            )
        ).scalars()
    )
    for a in issued:
        if a not in have:
            session.add(WatchedAddress(user_id=setting.user_id, network=setting.network, address=a, seen={}, baseline=False))
    await session.flush()


async def check_one(session: AsyncSession, row: WatchedAddress, client: httpx.AsyncClient, base: str) -> int:
    """Look at one address; queue messages for new or newly confirmed payments."""
    resp = await client.get(f"{base}/address/{row.address}/txs")
    resp.raise_for_status()
    seen: dict[str, str] = dict(row.seen or {})
    sent = 0
    for tx in resp.json():
        value = sum(o.get("value", 0) for o in tx.get("vout", []) if o.get("scriptpubkey_address") == row.address)
        if not value:
            continue
        txid = tx["txid"]
        now_state = "c" if tx.get("status", {}).get("confirmed") else "p"
        before = seen.get(txid)
        seen[txid] = now_state
        if not row.baseline or before == now_state or before == "c":
            continue
        kind = "wallet.received" if before is None else "wallet.confirmed"
        session.add(
            Notification(
                user_id=row.user_id,
                kind=kind,
                payload={"amount_sats": value, "txid": txid, "network": row.network, "confirmed": now_state == "c"},
            )
        )
        sent += 1
    if len(seen) > SEEN_KEEP:
        seen = dict(list(seen.items())[-SEEN_KEEP:])
    row.seen = seen
    row.baseline = True
    row.checked_at = _naive(datetime.now(UTC))
    return sent


async def sweep(session: AsyncSession, settings: Settings, *, client: httpx.AsyncClient | None = None) -> dict[str, int]:
    settings_rows = (
        await session.execute(select(WalletAlertSetting).where(WalletAlertSetting.enabled.is_(True)))
    ).scalars().all()
    for s in settings_rows:
        await _ensure_pool_rows(session, s)
    await session.commit()
    on = {(s.user_id, s.network) for s in settings_rows}
    request_addresses = set(
        (await session.execute(select(PaymentRequest.address).where(PaymentRequest.status == "open"))).scalars()
    )
    rows = (
        await session.execute(
            select(WatchedAddress).order_by(WatchedAddress.checked_at.is_not(None), WatchedAddress.checked_at).limit(MAX_PER_SWEEP)
        )
    ).scalars().all()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=10)
    checked = messages = errors = 0
    try:
        for row in rows:
            if (row.user_id, row.network) not in on or row.address in request_addresses:
                continue
            try:
                messages += await check_one(session, row, client, _esplora(settings, row.network))
                checked += 1
            except Exception as exc:  # one bad address must not stop the rest
                errors += 1
                log.warning("wallet_alert_check_failed", address=row.address, error=str(exc))
        await session.commit()
    finally:
        if owns:
            await client.aclose()
    return {"checked": checked, "messages": messages, "errors": errors}
