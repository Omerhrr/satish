"""Lightning service: payment_intents + XP ledger over a provider (D11).

Owns:
- PaymentIntent rows for both directions (receive: bolt11 invoice lifecycle;
  send: prepared -> authorized -> in_flight -> terminal fee-capped payment),
- the settlement gate: provider verification (preimage hashes to the
  payment_hash AND the node/provider confirms settled) -> CAS row transition
  pending -> settled -> ledger credit keyed ``purchase:{intent_id}``.
  Duplicate callbacks are structurally incapable of double-crediting: the
  race loser updates zero rows and the ledger idempotency key replays.
- ownership enforcement (every intent access is checked against user_id),
- liquidity/health disclosures for the API surface.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from lightning_adapter import (
    CannedLightningProvider,
    InvalidTransition,
    InvoiceExpired,
    InvoiceNotFound,
    LightningProviderError,
    PaymentNotFound,
    PaymentRejected,
    PaymentStatus,
    PaymentUncertain,
    PreparedPayment,
    make_lightning_provider,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.models.entities import PaymentIntent, User
from xp_core.services import ledger
from xp_core.services.ledger import LedgerResult

_provider: CannedLightningProvider | None = None
_provider_lock = threading.Lock()


def get_provider(settings: Settings) -> CannedLightningProvider:
    """Lazily build the process-wide provider from settings."""
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = make_lightning_provider(settings)  # type: ignore[assignment]
        return _provider


def reset_provider() -> None:
    """Test seam: drop the singleton so a new settings object takes effect."""
    global _provider
    with _provider_lock:
        _provider = None


# errors the router maps to HTTP


class LightningServiceError(Exception):
    pass


class AuthorizationMismatch(LightningServiceError):
    pass


# receive (invoice)


async def create_receive_intent(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    amount_sats: int,
    description: str,
) -> PaymentIntent:
    """Create a receive-side PaymentIntent with a live bolt11 invoice."""
    if amount_sats <= 0:
        raise ValueError("amount_sats must be positive")
    provider = get_provider(settings)
    amount_msat = amount_sats * 1000
    xp_amount = amount_sats * settings.xp_per_sat
    # Idempotency: one open invoice per (user, amount, description) intent -
    # a client retry creates a NEW intent (new idempotency key), never a
    # duplicate ledger effect, because credit is keyed on intent id.
    invoice = await provider.create_invoice(
        amount_msat=amount_msat,
        description=description,
        expiry_seconds=settings.lightning_invoice_expiry_seconds,
    )
    row = PaymentIntent(
        user_id=user.id,
        provider_reference=invoice.payment_hash,
        amount_sats=amount_sats,
        xp_amount=xp_amount,
        status="pending",
        direction="receive",
        bolt11=invoice.bolt11,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.lightning_invoice_expiry_seconds),
        idempotency_key=f"receive:{invoice.payment_hash}",
    )
    session.add(row)
    await session.flush()
    return row


async def get_owned_intent_by_hash(
    session: AsyncSession, user: User, payment_hash: str
) -> PaymentIntent:
    row = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.provider_reference == payment_hash,
                PaymentIntent.direction == "receive",
            )
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user.id:
        raise InvoiceNotFound("invoice not found")
    return row


def _invoice_elapsed(row: PaymentIntent, now: datetime) -> bool:
    if row.expires_at is None:
        return False
    # SQLite stores naive datetimes; normalize both sides to naive UTC.
    expires = row.expires_at if row.expires_at.tzinfo is None else row.expires_at.astimezone(UTC).replace(tzinfo=None)
    return now.astimezone(UTC).replace(tzinfo=None) >= expires


async def settle(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    payment_hash: str,
    preimage: str,
) -> dict:
    """Apply a settlement through the double gate.

    1. provider verification - the preimage must hash to the payment_hash
       (the real node's stream supplies it; this dev seam accepts the
       client's claim and verifies it cryptographically);
    2. CAS row transition pending -> settled (rowcount gate);
    3. ledger credit with idempotency key purchase:{intent_id}.

    Returns a disclosure dict; ``credited=False`` on a replay with an
    explicit note (never a silent duplicate credit, never an error).
    """
    row = await get_owned_intent_by_hash(session, user, payment_hash)
    provider = get_provider(settings)

    status, _inv = await provider.invoice_status(payment_hash)
    now = datetime.now(UTC)
    if status == "expired" or (row.status == "pending" and _invoice_elapsed(row, now)):
        if row.status == "pending":
            row.status = "expired"
        await session.commit()
        raise InvoiceExpired("invoice expired before settlement")

    try:
        first_settle = await provider.settle_invoice(payment_hash, preimage)
    except InvoiceExpired:
        if row.status == "pending":
            row.status = "expired"
        await session.commit()
        raise

    if not first_settle or row.status != "pending":
        await session.commit()
        return {
            "payment_hash": payment_hash,
            "status": row.status,
            "credited": False,
            "note": "settlement replay - this invoice was already credited",
        }

    # CAS transition: exactly one concurrent callback wins the row.
    result = await session.execute(
        update(PaymentIntent)
        .where(
            PaymentIntent.id == row.id,
            PaymentIntent.status == "pending",
        )
        .values(
            status="settled",
            settled_at=datetime.now(UTC),
        )
    )
    if result.rowcount == 0:
        await session.commit()
        return {
            "payment_hash": payment_hash,
            "status": row.status,
            "credited": False,
            "note": "settlement replay - this invoice was already credited",
        }

    outcome: LedgerResult = await ledger.credit_purchase(
        session,
        user_id=user.id,
        amount=row.xp_amount,
        payment_intent_id=row.id,
    )
    row.status = "settled"
    row.settled_at = datetime.now(UTC)
    await session.commit()
    return {
        "payment_hash": payment_hash,
        "status": "settled",
        "credited": not outcome.idempotent_replay,
        "xp_amount": row.xp_amount,
        "balance_after": outcome.balance_after,
        "note": None
        if not outcome.idempotent_replay
        else "ledger replay detected - credited exactly once",
    }


async def get_invoice_state(
    session: AsyncSession, *, user: User, settings: Settings, payment_hash: str
) -> PaymentIntent:
    """Read an owned invoice, ageing it out via the provider when elapsed."""
    row = await get_owned_intent_by_hash(session, user, payment_hash)
    if row.status == "pending":
        provider = get_provider(settings)
        status, _ = await provider.invoice_status(payment_hash)
        if status == "expired" or _invoice_elapsed(row, datetime.now(UTC)):
            row.status = "expired"
            await session.commit()
    return row


# send (payment)


async def prepare_send_intent(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    bolt11: str,
) -> tuple[PaymentIntent, PreparedPayment]:
    """Fee preview + authorization digest. Nothing moves; row is 'prepared'."""
    provider = get_provider(settings)
    prepared = await provider.prepare_payment(bolt11)
    row = PaymentIntent(
        user_id=user.id,
        provider_reference=prepared.payment_id,
        amount_sats=prepared.amount_msat // 1000,
        xp_amount=0,  # send side does not credit XP
        status="prepared",
        direction="send",
        bolt11=bolt11,
        fee_msat=prepared.fee_limit_msat,
        authorization_digest=prepared.authorization_digest,
        idempotency_key=f"send:{prepared.payment_id}",
    )
    session.add(row)
    await session.flush()
    return row, prepared


async def get_owned_intent_by_id(
    session: AsyncSession, user: User, payment_id: str
) -> PaymentIntent:
    row = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.provider_reference == payment_id,
                PaymentIntent.direction == "send",
            )
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user.id:
        raise PaymentNotFound("payment not found")
    return row


async def authorize_send_intent(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    payment_id: str,
    authorization_digest: str,
) -> PaymentIntent:
    """The digest the user reviewed must be presented back (mismatch -> 409).

    The DB stores the digest bound at prepare time; the presented value must
    match it exactly. The canned provider's own state machine is advanced
    after the check so submit sees an authorized record.
    """
    row = await get_owned_intent_by_id(session, user, payment_id)
    if row.status != "prepared":
        raise InvalidTransition(
            f"payment cannot move {row.status!r} -> authorized"
        )
    import hmac

    if not authorization_digest or not hmac.compare_digest(
        authorization_digest, row.authorization_digest or ""
    ):
        raise AuthorizationMismatch(
            "authorization digest does not bind the reviewed payment"
        )
    provider = get_provider(settings)
    if isinstance(provider, CannedLightningProvider):
        await provider.authorize_payment(payment_id, authorization_digest)
    row.status = "authorized"
    await session.commit()
    return row


async def _submit_via_provider(row: PaymentIntent, provider) -> PaymentStatus:
    """Normalize the two providers' submit semantics.

    canned: submit(payment_id) -> terminal PaymentStatus.
    lnd:    submit(bolt11, fee_limit_msat) -> terminal status or raises
            PaymentRejected (definite) / PaymentUncertain (unknown).
    """
    from lightning_adapter.lnd_provider import LndLightningProvider

    if isinstance(provider, LndLightningProvider):
        return await provider.submit_payment(
            bolt11=row.bolt11 or "", fee_limit_msat=row.fee_msat or 0
        )
    return await provider.submit_payment(row.provider_reference)


async def submit_send_intent(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    payment_id: str,
) -> dict:
    """Submit the authorized payment; terminal outcome or explicit uncertainty."""
    row = await get_owned_intent_by_id(session, user, payment_id)
    if row.status != "authorized":
        raise InvalidTransition(
            f"payment must be authorized before submit (state {row.status!r})"
        )
    provider = get_provider(settings)
    row.status = "in_flight"
    await session.commit()
    try:
        status = await _submit_via_provider(row, provider)
    except PaymentRejected:
        row.status = "failed"
        await session.commit()
        raise
    except InvoiceExpired:
        # Provider already recorded the failure; the DB row must agree.
        row.status = "failed"
        await session.commit()
        raise
    except (PaymentUncertain, LightningProviderError):
        # Outcome UNKNOWN: the row stays in_flight and a reconciliation pass
        # (payment_status) resolves it. Never silently retried.
        await session.commit()
        raise
    if status.status == "succeeded":
        row.status = "succeeded"
        row.fee_msat = status.fee_msat or row.fee_msat
    elif status.status == "failed":
        row.status = "failed"
    else:
        await session.commit()
        raise PaymentUncertain(
            "payment submitted but the node has not reported a terminal state"
        )
    await session.commit()
    return {
        "payment_id": payment_id,
        "status": row.status,
        "amount_sats": row.amount_sats,
        "fee_msat": row.fee_msat,
    }


# node surface


async def health(settings: Settings) -> dict:
    return await get_provider(settings).health()


async def channels(settings: Settings) -> dict:
    provider = get_provider(settings)
    rows = await provider.channels()
    outbound = sum(c["local_msat"] for c in rows)
    inbound = sum(c["remote_msat"] for c in rows)
    disclosures = [
        "Payments route over your channel liquidity; low capacity may cause "
        "failures until channels are opened or rebalanced.",
        f"Inbound capacity below {settings.lightning_min_inbound_msat} msat "
        "constrains what you can receive.",
    ]
    return {
        "channels": rows,
        "outbound_msat": outbound,
        "inbound_msat": inbound,
        "disclosures": disclosures,
        "inbound_constrained": inbound < settings.lightning_min_inbound_msat,
    }


def capabilities(settings: Settings) -> dict:
    provider = get_provider(settings)
    return {
        "mode": settings.lightning_mode,
        "network": settings.lightning_network,
        "implementation": provider.implementation,
        "invoice_expiry_seconds": settings.lightning_invoice_expiry_seconds,
        "fee_policy": {
            "base_fee_msat": settings.lightning_base_fee_msat,
            "fee_ppm": settings.lightning_fee_ppm,
            "max_fee_msat": settings.lightning_max_fee_msat,
            "note": "Payments are capped at the reviewed fee limit; the node "
            "rejects routes above it.",
        },
        "sats_to_xp": {
            "xp_per_sat": settings.xp_per_sat,
            "can_change": True,
            "note": "Phase-5 finalized conversion: credits are computed as "
            "sats * xp_per_sat at settle time; the published rate may still "
            "change, so clients re-check /api/v1/xp/rate.",
        },
        "custody_disclosure": [
            "In dev/test the provider is CANNED - deterministic in-memory "
            "semantics with no node attached; nothing here moves real funds.",
            "In lnd mode the node is self-hosted; channel backups (SCB) are "
            "required for recovery and the seed must be backed up with them.",
            "Mainnet is refused at construction pending the security review "
            "gate.",
        ],
    }


__all__ = [
    "LightningProviderError",
    "authorize_send_intent",
    "capabilities",
    "channels",
    "create_receive_intent",
    "get_invoice_state",
    "get_owned_intent_by_hash",
    "get_owned_intent_by_id",
    "get_provider",
    "health",
    "prepare_send_intent",
    "reset_provider",
    "settle",
    "submit_send_intent",
]
