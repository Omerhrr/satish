"""XP economy API (phase 5): rate, packs, purchases, receipts, reconciliation.

- /rate    published conversion, can_change: true (pricing_requirements #1)
- /packs   the published pack table (billing_flow #1)
- /purchases  create -> invoice; settlement credits via the lightning
              service's double gate ONLY; receipts are derived views over
              (intent, ledger entry) and the PDF is a worker artifact
- /reconcile  manual trigger of the reconciliation sweep (system seam; the
              worker also runs it on a schedule)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from xp_core.config import get_settings
from xp_core.jobs.reconciliation import reconcile_all
from xp_core.logging import get_logger
from xp_core.models.entities import Artifact, AuditEvent, XpLedgerEntry
from xp_core.pricing import rate_disclosure
from xp_core.schemas.api import (
    BalanceOut,
    DevGrantIn,
    LedgerEntryOut,
    LedgerPageOut,
    PackOut,
    PurchaseCreateIn,
    PurchaseOut,
    RateOut,
    ReconcileReportOut,
)
from xp_core.services import ledger
from xp_core.services.onchain import OnchainConfigError

from app.deps import CurrentUser, DbSession
from app.services import xp_service
from app.services.tk_lightning import TkLightningUnavailable

log = get_logger(__name__)
router = APIRouter(prefix="/xp", tags=["xp"])


@router.get("/rate", response_model=RateOut)
async def rate() -> RateOut:
    """Published sats->XP conversion (pricing_requirements #1)."""
    s = get_settings()
    return RateOut(
        **rate_disclosure(s),
        min_tk=s.tk_min_purchase,
        max_tk=s.tk_max_purchase,
        methods=xp_service.payment_methods(s),
        payee_username=(s.tk_payee_username or "").lstrip("@") or None,
        welcome_tk=s.tk_welcome_bonus,
    )


@router.get("/packs", response_model=list[PackOut])
async def packs() -> list[PackOut]:
    """The published XP pack table (billing_flow #1)."""
    return [PackOut(**p) for p in xp_service.pack_views(get_settings())]


@router.get("/balance", response_model=BalanceOut)
async def balance(user: CurrentUser, session: DbSession) -> BalanceOut:
    acct = await ledger.get_or_create_account(session, user.id)
    return BalanceOut(
        balance_xp=acct.balance, xp_per_sat=get_settings().xp_per_sat, updated_at=acct.updated_at
    )


@router.get("/ledger", response_model=LedgerPageOut)
async def ledger_entries(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LedgerPageOut:
    base = select(XpLedgerEntry).where(XpLedgerEntry.user_id == user.id)
    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(XpLedgerEntry.created_at.desc(), XpLedgerEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    items = [
        LedgerEntryOut(
            id=r.id,
            entry_type=r.entry_type,
            amount=r.amount,
            balance_after=r.balance_after,
            reference_type=r.reference_type,
            reference_id=r.reference_id,
            note=r.note,
            created_at=r.created_at,
        )
        for r in rows.scalars()
    ]
    return LedgerPageOut(items=items, total=int(total))


# purchases / receipts (billing_flow)


@router.post("/purchases", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
async def create_purchase(
    payload: PurchaseCreateIn, user: CurrentUser, session: DbSession
) -> PurchaseOut:
    """Choose a pack or enter a custom amount -> unique payment intent + invoice.

    Nothing is credited here; settlement only happens through the verified
    settle gate (never on client claims of payment).
    """
    settings = get_settings()
    try:
        row = await xp_service.create_purchase(
            session,
            user=user,
            settings=settings,
            pack_id=payload.pack_id,
            amount_sats=payload.amount_sats,
            description=payload.description,
            tk_amount=payload.tk_amount,
            method=payload.method,
        )
    except xp_service.UnknownPack as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OnchainConfigError, TkLightningUnavailable) as exc:
        log.error("payments_misconfigured", error=str(exc))
        raise HTTPException(status_code=503, detail="That payment method isn't set up yet. Try the other one.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.error("purchase_create_failed", error=type(exc).__name__, detail=str(exc)[:300])
        raise HTTPException(status_code=502, detail="Couldn't create the payment request. Please try again.") from exc
    await session.commit()
    out = xp_service.purchase_out(row)
    if out["payment_method"] == "onchain":
        out["network"] = settings.onchain_network
    return PurchaseOut(**out)


@router.get("/purchases", response_model=list[PurchaseOut])
async def list_purchases(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PurchaseOut]:
    rows = await xp_service.list_purchases(session, user, limit=limit, offset=offset)
    return [PurchaseOut(**xp_service.purchase_out(r)) for r in rows]


@router.get("/purchases/{purchase_id}", response_model=PurchaseOut)
async def get_purchase(purchase_id: str, user: CurrentUser, session: DbSession) -> PurchaseOut:
    """Read a purchase. On-chain requests are checked against the chain on
    each read so the app sees the credit as soon as the payment lands."""
    from xp_core.services import onchain

    row = await xp_service.get_owned_purchase(session, user, purchase_id)
    seen = None
    from app.services import tk_lightning

    if tk_lightning.is_tk_lightning(row) and row.status != "settled":
        try:
            await tk_lightning.settle_rows(session, [row], get_settings())
        except Exception as exc:
            log.warning("tk_lightning_check_failed", intent_id=row.id, error=type(exc).__name__)
    if onchain.is_onchain(row) and row.status != "settled":
        try:
            check = await onchain.settle_if_paid(session, row, get_settings())
            seen = check.seen_sats if check else None
        except Exception as exc:
            log.warning("onchain_check_failed", intent_id=row.id, error=str(exc))
    out = await xp_service.purchase_view(session, row)
    if onchain.is_onchain(row):
        out["network"] = get_settings().onchain_network
        out["seen_sats"] = seen
    return PurchaseOut(**out)


@router.post("/purchases/{purchase_id}/receipt.pdf", status_code=status.HTTP_202_ACCEPTED)
async def purchase_receipt_pdf(
    purchase_id: str, user: CurrentUser, session: DbSession
) -> dict:
    """Render the receipt PDF via the worker (inline in dev)."""
    row = await xp_service.get_owned_purchase(session, user, purchase_id)
    if row.status != "settled":
        raise HTTPException(
            status_code=409,
            detail=f"receipt available only for settled purchases (status: {row.status})",
        )
    artifact = Artifact(
        user_id=user.id,
        object_key=f"receipts/{row.id}/receipt.pdf",
        content_type="application/pdf",
        status="pending",
    )
    session.add(artifact)
    await session.commit()
    from app.worker_bridge import enqueue_receipt_pdf_job

    job_id = await enqueue_receipt_pdf_job(artifact_id=artifact.id, purchase_id=row.id)
    return {
        "artifact_id": artifact.id,
        "job_id": job_id,
        "status": "accepted",
        "download_url": f"/api/v1/artifacts/{artifact.id}/download",
    }


# reconciliation (system seam)


@router.post("/reconcile", response_model=ReconcileReportOut)
async def reconcile(user: CurrentUser, session: DbSession) -> ReconcileReportOut:
    """Run the full reconciliation sweep and audit any discrepancy.

    Manual/system seam for dev and ops; production relies on the worker's
    scheduled run. Gated to DEV_MODE like other administrative surfaces.
    """
    if not get_settings().dev_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="manual reconciliation is a system operation; use the scheduled worker job",
        )
    report = await reconcile_all(session)
    return ReconcileReportOut(**report)


@router.post("/dev/grant", response_model=BalanceOut)
async def dev_grant(payload: DevGrantIn, user: CurrentUser, session: DbSession) -> BalanceOut:
    """DEV_MODE-only administrative grant (never available in staging/prod)."""
    settings = get_settings()
    if not settings.dev_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="dev grants are disabled outside DEV_MODE",
        )
    await ledger.adjust(
        session,
        user_id=user.id,
        amount=payload.amount_xp,
        reason=payload.reason,
    )
    acct = await ledger.get_or_create_account(session, user.id)
    session.add(
        AuditEvent(
            actor_type="admin",
            actor_id=None,
            event_type="xp.dev_grant",
            resource_type="xp_account",
            resource_id=user.id,
            metadata_redacted={"amount_xp": payload.amount_xp, "reason": payload.reason},
        )
    )
    await session.commit()
    return BalanceOut(
        balance_xp=acct.balance, xp_per_sat=settings.xp_per_sat, updated_at=acct.updated_at
    )
