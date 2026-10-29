"""TK purchases paid over Lightning, into the operator's own wallet.

The operator's Lightning wallet (Breez SDK Spark, same kind as the in-app
wallet) runs inside the API with its phrase from XP_TK_LIGHTNING_MNEMONIC.
Each purchase gets its own BOLT11 invoice for the exact amount, so a
payment can only ever credit the purchase it was made for. Credit happens
once: the invoice must show up as a COMPLETED receive in the operator's
wallet, a compare-and-set moves the intent to settled, and the ledger entry
is keyed ``purchase:{intent_id}``.

The phrase can spend that wallet's funds, so the operator should sweep it
regularly and keep only a small float there (documented in deploy/README).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import PaymentIntent, User
from xp_core.services import ledger

log = get_logger(__name__)

REF_PREFIX = "tkln:"
EXPIRY_SECONDS = 3600
LATE_WINDOW_DAYS = 2


class TkLightningUnavailable(RuntimeError):
    pass


class PayeeWallet(Protocol):
    async def create_invoice(self, amount_sats: int, description: str, expiry_secs: int) -> str: ...
    async def paid_invoices(self, since_unix: int) -> set[str]: ...
    async def forward(self, destination: str, amount_sats: int, idempotency_key: str) -> str: ...


class BreezPayeeWallet:
    """The operator's wallet via the Breez SDK (lazy, one per process)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sdk = None
        self._lock = asyncio.Lock()

    async def _get(self):
        async with self._lock:
            if self._sdk is not None:
                return self._sdk
            import breez_sdk_spark as b  # heavy native module, import lazily

            s = self.settings
            network = b.Network.MAINNET if s.tk_lightning_network == "mainnet" else b.Network.REGTEST
            if network == b.Network.MAINNET and not s.breez_api_key:
                raise TkLightningUnavailable("mainnet Lightning needs XP_BREEZ_API_KEY")
            config = b.default_config(network=network)
            if s.breez_api_key:
                config.api_key = s.breez_api_key
            storage = os.path.join(s.tk_lightning_storage_dir, f"{s.tk_lightning_network}-{os.getpid()}")
            os.makedirs(storage, exist_ok=True)
            self._sdk = await b.connect(
                b.ConnectRequest(
                    config=config,
                    seed=b.Seed.MNEMONIC(mnemonic=" ".join((s.tk_ln_mnemonic or "").lower().split()), passphrase=None),
                    storage_dir=storage,
                )
            )
            log.info("tk_lightning_connected", network=s.tk_lightning_network)
            return self._sdk

    async def create_invoice(self, amount_sats: int, description: str, expiry_secs: int) -> str:
        import breez_sdk_spark as b

        sdk = await self._get()
        resp = await sdk.receive_payment(
            b.ReceivePaymentRequest(
                payment_method=b.ReceivePaymentMethod.BOLT11_INVOICE(
                    description=description,
                    amount_sats=amount_sats,
                    expiry_secs=expiry_secs,
                    payment_hash=None,
                    receiver_identity_public_key=None,
                )
            )
        )
        return resp.payment_request

    async def paid_invoices(self, since_unix: int) -> set[str]:
        import breez_sdk_spark as b

        sdk = await self._get()
        resp = await sdk.list_payments(
            b.ListPaymentsRequest(
                type_filter=[b.PaymentType.RECEIVE],
                status_filter=[b.PaymentStatus.COMPLETED],
                from_timestamp=since_unix,
                limit=500,
            )
        )
        out: set[str] = set()
        for p in resp.payments:
            inv = getattr(p.details, "invoice", None) if p.details is not None else None
            if inv:
                out.add(inv.lower())
        return out


_wallet: PayeeWallet | None = None


async def _breez_forward(self, destination: str, amount_sats: int, idempotency_key: str) -> str:
    """Send sats on to a developer's Lightning (Spark) address. Returns the payment id."""
    import breez_sdk_spark as b

    sdk = await self._get()
    prep = await sdk.prepare_send_payment(
        b.PrepareSendPaymentRequest(payment_request=b.PaymentRequest.INPUT(input=destination), amount=amount_sats)
    )
    resp = await sdk.send_payment(b.SendPaymentRequest(prepare_response=prep, idempotency_key=idempotency_key))
    return str(resp.payment.id)


BreezPayeeWallet.forward = _breez_forward  # type: ignore[attr-defined]


def get_wallet(settings: Settings) -> PayeeWallet:
    global _wallet
    if _wallet is None:
        if not settings.tk_ln_mnemonic:
            raise TkLightningUnavailable("Lightning TK payments need XP_TK_LIGHTNING_MNEMONIC")
        _wallet = BreezPayeeWallet(settings)
    return _wallet


def set_wallet(wallet: PayeeWallet | None) -> None:
    """Test seam."""
    global _wallet
    _wallet = wallet


def available(settings: Settings) -> bool:
    return bool(settings.tk_ln_mnemonic) or _wallet is not None


def is_tk_lightning(row: PaymentIntent) -> bool:
    return bool(row.provider_reference and row.provider_reference.startswith(REF_PREFIX))


async def create_intent(
    session: AsyncSession, *, user: User, settings: Settings, amount_sats: int, xp_amount: int
) -> PaymentIntent:
    wallet = get_wallet(settings)
    row = PaymentIntent(
        user_id=user.id,
        amount_sats=amount_sats,
        xp_amount=xp_amount,
        status="pending",
        direction="receive",
        expires_at=datetime.now(UTC) + timedelta(seconds=EXPIRY_SECONDS),
        idempotency_key="pending",  # replaced below once we have the invoice
    )
    session.add(row)
    await session.flush()
    bolt11 = await wallet.create_invoice(amount_sats, f"Satish TK {xp_amount:,} ({row.id[:8]})", EXPIRY_SECONDS)
    ref = REF_PREFIX + hashlib.sha256(bolt11.lower().encode()).hexdigest()
    row.bolt11 = bolt11
    row.provider_reference = ref
    row.idempotency_key = f"receive:{ref}"
    await session.flush()
    log.info("tk_lightning_invoice", intent_id=row.id, sats=amount_sats)
    return row


async def settle_rows(session: AsyncSession, rows: list[PaymentIntent], settings: Settings) -> int:
    rows = [r for r in rows if is_tk_lightning(r) and r.status != "settled" and r.bolt11]
    if not rows:
        return 0
    oldest = min(r.created_at for r in rows)
    since = int((oldest.replace(tzinfo=UTC) if oldest.tzinfo is None else oldest).timestamp()) - 60
    paid = await get_wallet(settings).paid_invoices(since)
    credited = 0
    now = datetime.now(UTC)
    for r in rows:
        if r.bolt11.lower() in paid:
            won = await session.execute(
                update(PaymentIntent)
                .where(PaymentIntent.id == r.id, PaymentIntent.status.in_(("pending", "expired")))
                .values(status="settled", settled_at=now)
            )
            if won.rowcount:
                await ledger.credit_purchase(session, user_id=r.user_id, amount=r.xp_amount, payment_intent_id=r.id)
                credited += 1
                log.info("tk_lightning_credited", intent_id=r.id, xp=r.xp_amount)
        elif r.status == "pending" and r.expires_at is not None:
            exp = r.expires_at if r.expires_at.tzinfo else r.expires_at.replace(tzinfo=UTC)
            if now >= exp:
                r.status = "expired"
    await session.commit()
    for r in rows:
        await session.refresh(r)
    return credited


async def sweep(session: AsyncSession, settings: Settings) -> dict[str, int]:
    if not available(settings):
        return {"checked": 0, "settled": 0}
    since = datetime.now(UTC) - timedelta(days=LATE_WINDOW_DAYS)
    rows = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.provider_reference.like(f"{REF_PREFIX}%"),
                PaymentIntent.status.in_(("pending", "expired")),
                PaymentIntent.created_at >= since.replace(tzinfo=None),
            )
        )
    ).scalars().all()
    settled = await settle_rows(session, list(rows), settings)
    return {"checked": len(rows), "settled": settled}
