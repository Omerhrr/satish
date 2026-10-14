"""XP balance, ledger, published rate, and dev-only seed grant."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from xp_core.config import get_settings
from xp_core.models.entities import AuditEvent, XpLedgerEntry
from xp_core.schemas.api import BalanceOut, DevGrantIn, LedgerEntryOut, LedgerPageOut
from xp_core.services import ledger

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/xp", tags=["xp"])


@router.get("/rate")
async def rate() -> dict[str, int | str]:
    """Published sats->XP conversion (pricing_requirements #1)."""
    settings = get_settings()
    return {"sats_per_xp": settings.sats_per_xp, "note": "conversion may change; always re-check"}


@router.get("/balance", response_model=BalanceOut)
async def balance(user: CurrentUser, session: DbSession) -> BalanceOut:
    acct = await ledger.get_or_create_account(session, user.id)
    return BalanceOut(
        balance_xp=acct.balance, sats_per_xp=get_settings().sats_per_xp, updated_at=acct.updated_at
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
        balance_xp=acct.balance, sats_per_xp=settings.sats_per_xp, updated_at=acct.updated_at
    )
