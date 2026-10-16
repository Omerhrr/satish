"""Ledger reconciliation job (phase 5, deliverable: Reconciliation job).

billing_flow #8: "Scheduled reconciliation flags discrepancies."

Three checks, all read-only until a discrepancy needs an audit record:

1. Per-user: xp_accounts.balance == SUM(xp_ledger_entries.amount).
   (ledger invariant #7.)
2. Settlement integrity: every SETTLED receive-direction payment intent has
   exactly one ``purchase`` ledger entry referencing it, and every purchase
   entry referencing a payment intent points at a settled receive intent.
   Together with the settle-time CAS + idempotency key this is the structural
   proof of acceptance criterion "One settled payment credits XP at most once".
3. Liveness: pending receive intents whose invoice has already expired are
   flagged so a sweep can age them out.

The job is deterministic backend code, runnable from the worker on a schedule
and from the API as a manual system trigger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.db import utcnow
from xp_core.logging import get_logger
from xp_core.models.entities import (
    AuditEvent,
    PaymentIntent,
    ReconciliationAlert,
    XpAccount,
    XpLedgerEntry,
)

log = get_logger(__name__)


async def reconcile_user(session: AsyncSession, user_id: str) -> dict[str, Any]:
    """balance == sum(entries) for one user (returns both sides)."""
    acct = (
        await session.execute(
            select(XpAccount).where(XpAccount.user_id == user_id)
        )
    ).scalar_one_or_none()
    balance = acct.balance if acct else 0
    row = (
        await session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM xp_ledger_entries WHERE user_id = :u"),
            {"u": user_id},
        )
    ).scalar_one()
    return {"user_id": user_id, "balance": balance, "sum_entries": int(row)}


async def reconcile_all(session: AsyncSession) -> dict[str, Any]:
    """Full reconciliation sweep; flags discrepancies and audits each one."""
    now = datetime.now(UTC)
    report: dict[str, Any] = {
        "checked_users": 0,
        "checked_settled_intents": 0,
        "checked_purchase_entries": 0,
        "discrepancies": [],
        "expired_pending_flagged": 0,
        "ok": True,
        "ran_at": now.isoformat(),
    }
    discrepancies = report["discrepancies"]

    # -- check 1: balance vs sum(entries) for every account -------------------
    balances: dict[str, dict[str, Any]] = {}
    accounts = (await session.execute(select(XpAccount))).scalars().all()
    report["checked_users"] = len(accounts)
    for acct in accounts:
        entry_sum = (
            await session.execute(
                select(func.coalesce(func.sum(XpLedgerEntry.amount), 0)).where(
                    XpLedgerEntry.user_id == acct.user_id
                )
            )
        ).scalar_one()
        balances[acct.user_id] = {"balance": acct.balance, "sum_entries": int(entry_sum)}
        if acct.balance != int(entry_sum):
            discrepancies.append(
                {
                    "kind": "balance_mismatch",
                    "user_id": acct.user_id,
                    "balance": acct.balance,
                    "sum_entries": int(entry_sum),
                }
            )
    # Ledger rows for users whose account row went missing entirely.
    orphan_sums = (
        await session.execute(
            select(XpLedgerEntry.user_id, func.sum(XpLedgerEntry.amount))
            .group_by(XpLedgerEntry.user_id)
        )
    ).all()
    for user_id, total in orphan_sums:
        if user_id not in balances:
            discrepancies.append(
                {
                    "kind": "missing_account_row",
                    "user_id": user_id,
                    "sum_entries": int(total),
                }
            )

    # -- check 2: settled receive intents <-> purchase entries, 1:1 -----------
    settled_intents = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.direction == "receive",
                PaymentIntent.status == "settled",
            )
        )
    ).scalars().all()
    report["checked_settled_intents"] = len(settled_intents)

    purchase_entries = (
        await session.execute(
            select(XpLedgerEntry).where(
                XpLedgerEntry.entry_type == "purchase",
                XpLedgerEntry.reference_type == "payment_intent",
            )
        )
    ).scalars().all()
    report["checked_purchase_entries"] = len(purchase_entries)

    intent_ids = {i.id for i in settled_intents}
    entries_by_intent: dict[str, list[XpLedgerEntry]] = {}
    for entry in purchase_entries:
        entries_by_intent.setdefault(entry.reference_id or "", []).append(entry)

    for intent in settled_intents:
        linked = entries_by_intent.get(intent.id, [])
        if len(linked) == 0:
            discrepancies.append(
                {
                    "kind": "settled_intent_without_purchase_entry",
                    "payment_intent_id": intent.id,
                    "user_id": intent.user_id,
                    "xp_amount": intent.xp_amount,
                }
            )
        elif len(linked) > 1:
            discrepancies.append(
                {
                    "kind": "purchase_credited_more_than_once",
                    "payment_intent_id": intent.id,
                    "user_id": intent.user_id,
                    "entry_count": len(linked),
                    "entry_ids": [e.id for e in linked],
                }
            )
    for entry in purchase_entries:
        if entry.reference_id not in intent_ids:
            discrepancies.append(
                {
                    "kind": "purchase_entry_without_settled_intent",
                    "ledger_entry_id": entry.id,
                    "payment_intent_id": entry.reference_id,
                    "user_id": entry.user_id,
                }
            )

    # -- check 3: pending receive intents past their expiry -------------------
    pending = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.direction == "receive",
                PaymentIntent.status == "pending",
                PaymentIntent.expires_at.is_not(None),
            )
        )
    ).scalars().all()
    expired_subjects: set[str] = set()
    expired_details: list[dict[str, Any]] = []
    for intent in pending:
        expires = intent.expires_at
        if expires is None:
            continue
        if expires.tzinfo is not None:
            expires = expires.astimezone(UTC).replace(tzinfo=None)
        if now.replace(tzinfo=None) >= expires:
            report["expired_pending_flagged"] += 1
            expired_subjects.add(intent.id)
            expired_details.append(
                {
                    "kind": "expired_pending",
                    "payment_intent_id": intent.id,
                    "user_id": intent.user_id,
                    "expires_at": intent.expires_at.isoformat() if intent.expires_at else None,
                    "expected": "settled or expired before sweep",
                    "observed": "pending past expiry",
                }
            )

    # -- alert persistence (phase 10: payment reconciliation alerts) ----------
    # Every discrepancy becomes/updates an operator-facing alert row.
    #   critical kinds  -> money integrity; NEVER auto-resolved (a mismatch
    #                      that "goes away" is itself evidence worth keeping).
    #   warning kinds   -> housekeeping; auto-resolve when the underlying
    #                      condition stops being observed.
    # Dedupe: one live (open|acknowledged) alert per (kind, subject); repeat
    # sightings bump last_seen_at and refresh the detail instead of stacking.
    CRITICAL_KINDS = {
        "balance_mismatch",
        "missing_account_row",
        "settled_intent_without_purchase_entry",
        "purchase_credited_more_than_once",
        "purchase_entry_without_settled_intent",
    }

    def _subject(d: dict[str, Any]) -> str:
        return str(
            d.get("user_id")
            or d.get("payment_intent_id")
            or d.get("ledger_entry_id")
            or "unknown"
        )

    live = (
        await session.execute(
            select(ReconciliationAlert).where(
                ReconciliationAlert.status.in_(["open", "acknowledged"])
            )
        )
    ).scalars().all()
    live_index = {(a.kind, a.subject): a for a in live}

    opened = updated = 0
    for d in [*discrepancies, *expired_details]:
        kind = d["kind"]
        subject = _subject(d)
        severity = "critical" if kind in CRITICAL_KINDS else "warning"
        # Ledger is authoritative: expected = what entries sum to,
        # observed = what the account row claims.
        expected = d.get("expected") or (
            str(d["sum_entries"])
            if kind == "balance_mismatch" and "sum_entries" in d
            else None
        )
        observed = d.get("observed") or (
            str(d["balance"]) if kind == "balance_mismatch" and "balance" in d else None
        )
        existing = live_index.get((kind, subject))
        if existing is not None:
            existing.last_seen_at = utcnow()
            existing.expected = expected
            existing.observed = observed
            existing.detail = d
            updated += 1
        else:
            session.add(
                ReconciliationAlert(
                    kind=kind,
                    severity=severity,
                    subject=subject,
                    expected=expected,
                    observed=observed,
                    detail=d,
                    status="open",
                )
            )
            opened += 1

    # Housekeeping warnings auto-resolve when no longer observed; critical
    # alerts stay live until an operator resolves them explicitly.
    auto_resolved = 0
    for a in live:
        if a.status == "resolved":
            continue
        if a.kind == "expired_pending" and a.subject not in expired_subjects:
            a.status = "resolved"
            a.resolved_at = utcnow()
            a.resolved_note = "auto-resolved: pending intent no longer expired at sweep time"
            auto_resolved += 1

    if discrepancies:
        report["ok"] = False
        for d in discrepancies:
            session.add(
                AuditEvent(
                    actor_type="system",
                    event_type="xp.reconciliation_flag",
                    resource_type="xp_ledger",
                    resource_id=d.get("user_id") or d.get("payment_intent_id"),
                    metadata_redacted={"kind": d["kind"], "detail": d},
                )
            )
    report["alerts_opened"] = opened
    report["alerts_updated"] = updated
    report["alerts_auto_resolved"] = auto_resolved
    await session.flush()
    await session.commit()
    log.info(
        "xp_reconciliation_complete",
        ok=report["ok"],
        users=report["checked_users"],
        discrepancies=len(discrepancies),
        alerts_opened=opened,
        alerts_updated=updated,
        alerts_auto_resolved=auto_resolved,
    )
    return report


__all__ = ["reconcile_all", "reconcile_user"]
