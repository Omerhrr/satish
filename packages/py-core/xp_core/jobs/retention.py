"""Privacy and retention sweep (phase 10, deliverable: Privacy and retention policy
enforcement).

The policy itself lives in docs/privacy-retention.md; this job is the
enforcement arm. Windows are settings (XP_RETENTION_*), each sweep deletes
ONLY within its window and never touches the money trail or audit surfaces:

- xp_ledger_entries / xp_accounts / payment_intents  -> NEVER (append-only
  money trail; reconciliation depends on it).
- task_events / audit_events                         -> NEVER (append-only
  evidence trail).
- artifacts                                          -> NEVER automatically
  (user deliverables; explicit user delete is the documented path).
- sessions        -> expired or revoked rows older than
                     retention_sessions_days (default 7).
- notifications   -> read rows older than retention_notifications_read_days
                     (default 30); unread rows older than
                     retention_notifications_unread_days (default 90) so an
                     unrelayed notification cannot silently vanish.
- automation_runs -> finished rows older than retention_automation_runs_days
                     (default 180). Runs still referenced by an unresolved
                     approval flow are protected via finished_at only.
- email_drafts    -> terminal-status drafts (sent|failed|refused|
                     unknown_outcome) with sent_at/updated_at older than
                     retention_email_drafts_sent_days (default 30). Drafted
                     drafts are never swept (user content pending a decision).

The sweep is deterministic backend code: the worker runs it daily; tests run
it directly. Every run returns a per-table deleted/preserved report and logs
a single structured event (privacy: counts only, never row content).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import get_settings
from xp_core.logging import get_logger
from xp_core.models.entities import (
    AuditEvent,
    AutomationRun,
    EmailDraft,
    Notification,
    PaymentIntent,
    Session,
    TaskEvent,
    XpLedgerEntry,
)

log = get_logger(__name__)

TERMINAL_DRAFT_STATUSES = ("sent", "failed", "refused", "unknown_outcome")

# Surfaces this sweep is forbidden to touch, reported verbatim so the report
# itself proves the boundary.
PRESERVED_SURFACES = [
    "xp_ledger_entries",
    "xp_accounts",
    "payment_intents",
    "task_events",
    "audit_events",
    "artifacts",
    "research_sources",
]


def _naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


async def retention_sweep(session: AsyncSession, now: datetime | None = None) -> dict[str, Any]:
    """Delete expired rows within configured windows; return an honest report."""
    settings = get_settings()
    now = _naive(now or datetime.now(UTC))
    report: dict[str, Any] = {"ran_at": now.isoformat(), "deleted": {}, "preserved": PRESERVED_SURFACES}

    # -- sessions --------------------------------------------------------------
    session_cutoff = now - timedelta(days=settings.retention_sessions_days)
    res = await session.execute(
        delete(Session).where(
            (Session.expires_at < session_cutoff)
            | (Session.revoked_at.is_not(None) & (Session.revoked_at < session_cutoff))
        )
    )
    report["deleted"]["sessions"] = res.rowcount

    # -- notifications ----------------------------------------------------------
    read_cutoff = now - timedelta(days=settings.retention_notifications_read_days)
    unread_cutoff = now - timedelta(days=settings.retention_notifications_unread_days)
    res = await session.execute(
        delete(Notification).where(
            (Notification.read_at.is_not(None) & (Notification.read_at < read_cutoff))
            | (Notification.read_at.is_(None) & (Notification.created_at < unread_cutoff))
        )
    )
    report["deleted"]["notifications"] = res.rowcount

    # -- automation runs (finished ones only) ------------------------------------
    run_cutoff = now - timedelta(days=settings.retention_automation_runs_days)
    res = await session.execute(
        delete(AutomationRun).where(
            AutomationRun.finished_at.is_not(None) & (AutomationRun.finished_at < run_cutoff)
        )
    )
    report["deleted"]["automation_runs"] = res.rowcount

    # -- terminal email drafts ----------------------------------------------------
    draft_cutoff = now - timedelta(days=settings.retention_email_drafts_sent_days)
    res = await session.execute(
        delete(EmailDraft).where(
            EmailDraft.status.in_(TERMINAL_DRAFT_STATUSES)
            & (
                (EmailDraft.sent_at.is_not(None) & (EmailDraft.sent_at < draft_cutoff))
                | (EmailDraft.sent_at.is_(None) & (EmailDraft.updated_at < draft_cutoff))
            )
        )
    )
    report["deleted"]["email_drafts"] = res.rowcount

    await session.commit()
    log.info("retention_sweep_complete", deleted=report["deleted"])
    return report


async def retention_proof(session: AsyncSession) -> dict[str, int]:
    """Read-only counters proving the preserved surfaces still exist (drill aid)."""
    out: dict[str, int] = {}
    out["xp_ledger_entries"] = len(
        (await session.execute(select(XpLedgerEntry.id))).all()
    )
    out["payment_intents"] = len(
        (await session.execute(select(PaymentIntent.id))).all()
    )
    out["task_events"] = len((await session.execute(select(TaskEvent.id))).all())
    out["audit_events"] = len((await session.execute(select(AuditEvent.id))).all())
    return out


__all__ = ["PRESERVED_SURFACES", "retention_proof", "retention_sweep"]
