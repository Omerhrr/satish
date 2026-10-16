"""Lightning API (phase 4, decision D11).

Receive:  POST /invoices -> bolt11; settlement applies through the double
          gate (preimage verification + CAS + ledger idempotency) so a
          duplicate callback can never double-credit.
Send:     prepare (fee preview + digest, nothing moves) -> authorize (the
          reviewed digest must come back) -> submit (fee cap enforced at the
          node; uncertain outages are explicit 504s).

Disclosures: /capabilities states the canned provider verbatim in dev/test,
/channels discloses liquidity constraints, custody notes and the sats->XP
conversion (published, can change). Mainnet is refused at the provider.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from lightning_adapter import (
    AuthorizationMismatch as ProviderAuthorizationMismatch,
)
from lightning_adapter import (
    InvalidTransition,
    InvoiceExpired,
    InvoiceNotFound,
    LightningProviderError,
    NodeUnavailable,
    PaymentNotFound,
    PaymentRejected,
    PaymentUncertain,
    PreimageMismatch,
)
from lightning_adapter.canned import InvoiceNotFound as CannedInvoiceNotFound
from pydantic import BaseModel, Field

from app.deps import CurrentUser, DbSession, SettingsDep
from app.services import lightning_service as svc

router = APIRouter(prefix="/lightning", tags=["lightning"])


# schemas


class InvoiceCreateIn(BaseModel):
    amount_sats: int = Field(gt=0, le=100_000_000)
    description: str = Field(default="", max_length=500)


class SettleIn(BaseModel):
    preimage: str = Field(min_length=64, max_length=64)


class PaymentPrepareIn(BaseModel):
    bolt11: str = Field(min_length=8, max_length=2048)


class PaymentAuthorizeIn(BaseModel):
    authorization_digest: str = Field(min_length=64, max_length=64)


def _intent_out(row) -> dict:
    return {
        "payment_hash": row.provider_reference or "",
        "id": row.id,
        "direction": row.direction,
        "amount_sats": row.amount_sats,
        "xp_amount": row.xp_amount,
        "status": row.status,
        "bolt11": row.bolt11,
        "fee_msat": row.fee_msat,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _http_error(exc: Exception) -> HTTPException:
    mapping = {
        InvoiceNotFound: 404,
        CannedInvoiceNotFound: 404,
        PaymentNotFound: 404,
        InvalidTransition: 409,
        ProviderAuthorizationMismatch: 409,
        svc.AuthorizationMismatch: 409,
        InvoiceExpired: 410,
        PreimageMismatch: 400,
        PaymentRejected: 422,
        NodeUnavailable: 503,
        PaymentUncertain: 504,
        ValueError: 422,
    }
    code = mapping.get(type(exc), 500)
    return HTTPException(status_code=code, detail=str(exc))


# capabilities / node surface


@router.get("/capabilities")
def get_capabilities(settings: SettingsDep) -> dict:
    return svc.capabilities(settings)


@router.get("/health")
async def get_health(settings: SettingsDep) -> dict:
    try:
        return await svc.health(settings)
    except LightningProviderError as exc:
        raise _http_error(exc) from exc


@router.get("/channels")
async def get_channels(settings: SettingsDep) -> dict:
    try:
        return await svc.channels(settings)
    except LightningProviderError as exc:
        raise _http_error(exc) from exc


# receive


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    body: InvoiceCreateIn, user: CurrentUser, session: DbSession, settings: SettingsDep
) -> dict:
    try:
        row = await svc.create_receive_intent(
            session,
            user=user,
            settings=settings,
            amount_sats=body.amount_sats,
            description=body.description,
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return _intent_out(row)


@router.get("/invoices/{payment_hash}")
async def get_invoice(
    payment_hash: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    try:
        row = await svc.get_invoice_state(
            session, user=user, settings=settings, payment_hash=payment_hash
        )
    except InvoiceNotFound as exc:
        raise _http_error(exc) from exc
    return _intent_out(row)


@router.post("/invoices/{payment_hash}/settle")
async def settle_invoice(
    payment_hash: str,
    body: SettleIn,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """Apply a settlement (dev seam: the production caller is the node's
    invoice-settled stream with the node-supplied preimage)."""
    try:
        return await svc.settle(
            session,
            user=user,
            settings=settings,
            payment_hash=payment_hash,
            preimage=body.preimage,
        )
    except (LightningProviderError, InvalidTransition, InvoiceExpired) as exc:
        raise _http_error(exc) from exc
    except svc.LightningServiceError as exc:
        raise _http_error(exc) from exc


@router.post("/invoices/{payment_hash}/settle-dev")
async def settle_invoice_dev(
    payment_hash: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """DEV_MODE-only auto-settle: the backend pulls the preimage from the
    canned provider itself so the Mini App can exercise the full billing
    flow without handling preimages. Refused outside dev/canned mode -
    production settlement arrives exclusively from the node's stream."""
    from lightning_adapter import CannedLightningProvider

    if not settings.dev_mode:
        raise HTTPException(status_code=403, detail="dev settle is disabled outside DEV_MODE")
    provider = svc.get_provider(settings)
    if not isinstance(provider, CannedLightningProvider):
        raise HTTPException(
            status_code=409,
            detail="dev settle requires the canned provider; production settles via the node",
        )
    record = provider._invoices.get(payment_hash)  # white-box dev seam
    if record is None:
        raise HTTPException(status_code=404, detail="invoice not found")
    try:
        return await svc.settle(
            session,
            user=user,
            settings=settings,
            payment_hash=payment_hash,
            preimage=record.invoice.preimage,
        )
    except (LightningProviderError, InvalidTransition, InvoiceExpired) as exc:
        raise _http_error(exc) from exc
    except svc.LightningServiceError as exc:
        raise _http_error(exc) from exc


# send


@router.post("/payments/prepare", status_code=status.HTTP_201_CREATED)
async def prepare_payment(
    body: PaymentPrepareIn,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    """Fee preview + authorization digest. Nothing moves."""
    try:
        _row, prepared = await svc.prepare_send_intent(
            session, user=user, settings=settings, bolt11=body.bolt11
        )
    except LightningProviderError as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return {
        "payment_id": prepared.payment_id,
        "state": prepared.state,
        "amount_msat": prepared.amount_msat,
        "fee_estimate_msat": prepared.fee_estimate_msat,
        "fee_limit_msat": prepared.fee_limit_msat,
        "fee_clamped": prepared.fee_clamped,
        "authorization_digest": prepared.authorization_digest,
        "description": prepared.description,
        "note": "Nothing has moved; presenting this digest back at authorize "
        "binds the reviewed amount and fee cap.",
    }


@router.post("/payments/{payment_id}/authorize")
async def authorize_payment(
    payment_id: str,
    body: PaymentAuthorizeIn,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    try:
        row = await svc.authorize_send_intent(
            session,
            user=user,
            settings=settings,
            payment_id=payment_id,
            authorization_digest=body.authorization_digest,
        )
    except (LightningProviderError, svc.LightningServiceError, InvalidTransition) as exc:
        raise _http_error(exc) from exc
    return _intent_out(row)


@router.post("/payments/{payment_id}/submit")
async def submit_payment(
    payment_id: str,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> dict:
    try:
        return await svc.submit_send_intent(
            session, user=user, settings=settings, payment_id=payment_id
        )
    except (LightningProviderError, InvalidTransition) as exc:
        raise _http_error(exc) from exc


@router.get("/payments/{payment_id}")
async def get_payment(
    payment_id: str, user: CurrentUser, session: DbSession
) -> dict:
    try:
        row = await svc.get_owned_intent_by_id(session, user, payment_id)
    except PaymentNotFound as exc:
        raise _http_error(exc) from exc
    return _intent_out(row)
