"""Lightning for developer payment requests.

The developer's Lightning wallet lives on their phone, so the server can't
see payments to it. For API payment requests Satish therefore receives the
payment itself and forwards it:

1. On creation, Satish's own Lightning wallet (the operator wallet, see
   tk_lightning) makes an invoice for the exact amount.
2. Every few seconds the API checks that wallet; a paid invoice marks the
   request paid (paid_via=lightning), notifies the owner and queues the
   request.paid webhook straight away.
3. The sats are forwarded to the owner's published Lightning (Spark) address,
   with a stable idempotency key per request so a retry can't pay twice.
   Spark-to-Spark transfers have no fee. Failed forwards retry; after 6 tries
   the request is marked forward_status=failed for the operator to settle.

Satish holds the money only between those two steps (normally seconds).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import Notification, PaymentRequest, WalletHandle
from xp_core.services import handles as svc
from xp_core.services.webhooks import queue_event

from app.services import tk_lightning

log = get_logger(__name__)

INVOICE_EXPIRY = 24 * 3600
MAX_FORWARD_ATTEMPTS = 6


class NoLightning(RuntimeError):
    pass


def lightning_ready(settings: Settings, handle: WalletHandle | None) -> str | None:
    """Why Lightning can't be offered for this owner, or None if it can."""
    if not tk_lightning.available(settings):
        return "Lightning payments aren't set up on this Satish server yet."
    if handle is None or not handle.spark_address:
        return "Open Lightning once in your Satish wallet so payments can be forwarded to it."
    if handle.spark_network and handle.spark_network != settings.tk_lightning_network:
        return f"Your Lightning wallet is on {handle.spark_network}; this server uses {settings.tk_lightning_network}."
    return None


async def attach_invoice(session: AsyncSession, req: PaymentRequest, handle: WalletHandle, settings: Settings) -> None:
    if not req.amount_sats:
        raise NoLightning("Lightning needs an amount.")
    why = lightning_ready(settings, handle)
    if why:
        raise NoLightning(why)
    desc = f"Satish · @{req.username}" + (f" · {req.note}" if req.note else "")
    req.ln_invoice = await tk_lightning.get_wallet(settings).create_invoice(req.amount_sats, desc[:120], INVOICE_EXPIRY)
    req.ln_destination = handle.spark_address


def _key(req: PaymentRequest) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"satish-forward/{req.id}"))


async def settle(session: AsyncSession, rows: list[PaymentRequest], settings: Settings) -> int:
    """Mark paid any open request whose Lightning invoice was paid."""
    rows = [r for r in rows if r.ln_invoice and r.status == "open"]
    if not rows or not tk_lightning.available(settings):
        return 0
    oldest = min(r.created_at for r in rows)
    since = int(oldest.replace(tzinfo=UTC).timestamp()) - 60
    paid = await tk_lightning.get_wallet(settings).paid_invoices(since)
    n = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    for r in rows:
        if r.ln_invoice.lower() not in paid:
            continue
        r.status = "paid"
        r.paid_via = "lightning"
        r.paid_sats = r.amount_sats or 0
        r.paid_at = now
        r.forward_status = "pending"
        session.add(Notification(user_id=r.user_id, kind="request.paid",
                                 payload={"request_id": r.id, "amount_sats": r.paid_sats, "note": r.note, "username": r.username}))
        await queue_event(session, r.user_id, "request.paid", {**svc.request_public(r), "paid_via": "lightning"})
        n += 1
        log.info("dev_lightning_paid", request_id=r.id, sats=r.paid_sats)
    await session.commit()
    return n


async def forward_pending(session: AsyncSession, settings: Settings) -> dict[str, int]:
    rows = (
        await session.execute(select(PaymentRequest).where(PaymentRequest.forward_status == "pending").limit(50))
    ).scalars().all()
    sent = failed = 0
    wallet = tk_lightning.get_wallet(settings) if rows else None
    for r in rows:
        r.forward_attempts = (r.forward_attempts or 0) + 1
        try:
            r.forward_ref = await wallet.forward(r.ln_destination, r.paid_sats or r.amount_sats or 0, _key(r))  # type: ignore[union-attr]
            r.forward_status = "sent"
            r.forward_error = None
            sent += 1
            log.info("dev_lightning_forwarded", request_id=r.id, sats=r.paid_sats)
        except Exception as exc:
            r.forward_error = f"{type(exc).__name__}: {exc}"[:300]
            if r.forward_attempts >= MAX_FORWARD_ATTEMPTS:
                r.forward_status = "failed"
                failed += 1
                log.error("dev_lightning_forward_failed", request_id=r.id, error=r.forward_error)
        await session.commit()
    return {"forwarded": sent, "failed": failed}


async def sweep(session: AsyncSession, settings: Settings) -> dict[str, int]:
    since = (datetime.now(UTC) - timedelta(days=2)).replace(tzinfo=None)
    rows = (
        await session.execute(
            select(PaymentRequest).where(
                PaymentRequest.status == "open", PaymentRequest.ln_invoice.is_not(None), PaymentRequest.created_at >= since
            )
        )
    ).scalars().all()
    paid = await settle(session, list(rows), settings)
    fwd = await forward_pending(session, settings)
    return {"checked": len(rows), "paid": paid, **fwd}
