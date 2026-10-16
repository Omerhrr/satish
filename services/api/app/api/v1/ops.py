"""Ops router (phase 10): reconciliation alerts + observability summary.

System seam, DEV_MODE-gated like /xp/reconcile: in production these read/
write ops queues run behind the operator's own access control (documented in
docs/incident-response.md); exposing them publicly would leak money-integrity
state, so this build refuses outside DEV_MODE.

Nothing here mutates balances — alerts are a queue over the ledger, the
ledger stays authoritative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from xp_core.config import get_settings
from xp_core.models.entities import ReconciliationAlert
from xp_core.schemas.api import (
    AlertAckOut,
    ObservabilityOut,
    ReconciliationAlertOut,
    ReconciliationAlertsPageOut,
)

from app.deps import DbSession

router = APIRouter(prefix="/ops", tags=["ops"])


def _require_dev() -> None:
    if not get_settings().dev_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ops surfaces are operator-only; disabled outside DEV_MODE in this build",
        )


def _view(a: ReconciliationAlert) -> ReconciliationAlertOut:
    return ReconciliationAlertOut(
        id=a.id,
        kind=a.kind,
        severity=a.severity,
        subject=a.subject,
        expected=a.expected,
        observed=a.observed,
        detail=a.detail,
        status=a.status,
        first_seen_at=a.first_seen_at,
        last_seen_at=a.last_seen_at,
        acknowledged_at=a.acknowledged_at,
        resolved_at=a.resolved_at,
        resolved_note=a.resolved_note,
    )


async def _counts(session: DbSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ReconciliationAlert.status, ReconciliationAlert.severity, func.count())
            .group_by(ReconciliationAlert.status, ReconciliationAlert.severity)
        )
    ).all()
    out = {"open_critical": 0, "open_warning": 0, "resolved_total": 0}
    for st, sev, n in rows:
        if st in ("open", "acknowledged") and sev == "critical":
            out["open_critical"] += n
        elif st in ("open", "acknowledged"):
            out["open_warning"] += n
        elif st == "resolved":
            out["resolved_total"] += n
    return out


@router.get("/reconciliation/alerts", response_model=ReconciliationAlertsPageOut)
async def list_alerts(
    session: DbSession,
    include_resolved: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> ReconciliationAlertsPageOut:
    """Operator queue of payment/ledger discrepancy alerts (phase 10)."""
    _require_dev()
    base = select(ReconciliationAlert)
    if not include_resolved:
        base = base.where(ReconciliationAlert.status.in_(["open", "acknowledged"]))
    rows = (
        (
            await session.execute(
                base.order_by(ReconciliationAlert.last_seen_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    counts = await _counts(session)
    return ReconciliationAlertsPageOut(
        alerts=[_view(a) for a in rows],
        open_critical=counts["open_critical"],
        open_warning=counts["open_warning"],
    )


@router.post("/reconciliation/alerts/{alert_id}/ack", response_model=AlertAckOut)
async def ack_alert(alert_id: str, session: DbSession) -> AlertAckOut:
    """Acknowledge an alert: an operator has seen it (investigation started)."""
    _require_dev()
    alert = (
        await session.execute(select(ReconciliationAlert).where(ReconciliationAlert.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert not found")
    if alert.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="alert already resolved"
        )
    if alert.status != "acknowledged":
        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.now(UTC)
        await session.commit()
    return AlertAckOut(id=alert.id, status=alert.status, acknowledged_at=alert.acknowledged_at)


@router.post("/reconciliation/alerts/{alert_id}/resolve", response_model=AlertAckOut)
async def resolve_alert(
    alert_id: str, session: DbSession, note: str = Query(default="", max_length=280)
) -> AlertAckOut:
    """Explicit operator resolution with a required-trail note.

    Critical alerts are never auto-resolved by the sweep (a money-integrity
    mismatch that "disappears" is itself evidence) — this endpoint is the
    ONLY path to resolved for them.
    """
    _require_dev()
    alert = (
        await session.execute(select(ReconciliationAlert).where(ReconciliationAlert.id == alert_id))
    ).scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert not found")
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_at = datetime.now(UTC)
        alert.resolved_note = note or "resolved by operator"
        await session.commit()
    return AlertAckOut(id=alert.id, status=alert.status, acknowledged_at=alert.acknowledged_at)


@router.get("/observability", response_model=ObservabilityOut)
async def observability(session: DbSession) -> ObservabilityOut:
    """Ops summary: alert counts + policy echo. Counts only, never content."""
    _require_dev()
    settings = get_settings()
    counts = await _counts(session)
    return ObservabilityOut(
        env=settings.env,
        reconcile_interval_seconds=settings.reconcile_interval_seconds,
        alerts_open_critical=counts["open_critical"],
        alerts_open_warning=counts["open_warning"],
        alerts_resolved_total=counts["resolved_total"],
        rate_limit_enabled=settings.rate_limit_enabled,
        retention_policy={
            "sessions_days": settings.retention_sessions_days,
            "notifications_read_days": settings.retention_notifications_read_days,
            "notifications_unread_days": settings.retention_notifications_unread_days,
            "automation_runs_days": settings.retention_automation_runs_days,
            "email_drafts_sent_days": settings.retention_email_drafts_sent_days,
        },
    )


__all__: list[Any] = ["router"]
