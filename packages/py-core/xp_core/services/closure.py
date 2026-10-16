"""Self-serve account export + closure (KL-10).

Two operations with an explicit, honest contract:

``export_user_data`` - one JSON document with every surface the user owns.
Secret material (session token hashes, Fernet credential ciphertexts) is
NEVER exported - the response discloses that.

``close_account`` - the documented ledger-aware erasure flow:
1. preconditions are checked first and closure REFUSES with precise reasons
   while anything is in flight (running tasks, pending approvals, money in
   motion, nonzero XP balance - there is no fabricated "forfeit" ledger
   entry; balance must reach zero through real economic events);
2. reconciliation must be clean (balance == sum of ledger entries) before
   any erasure - the documented "reconcile the immutable ledger before
   anonymizing identity rows" rule;
3. user content is hard-deleted (sessions, notifications, drafts,
   credentials, connections, approvals, run history, provenance, task
   steps, artifact rows + files, wallet server state);
4. identity rows are anonymized (telegram linkage deleted, display name
   dropped, status=closed) while the user row itself stays as the FK anchor
   for the permanent money/evidence trail;
5. content-bearing fields of structural rows are scrubbed in place (task
   objectives, job templates) so append-only evidence (task_events, ledger,
   payment intents, audit events) stays intact and resolvable.

PRESERVED_SURFACES governs the automatic retention sweep; closure is an
explicit authenticated user action and may delete sweep-preserved
user-content surfaces (artifacts, research_sources) - but NEVER the money
and evidence trail (xp_ledger_entries, payment_intents, xp_accounts,
task_events, audit_events).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.jobs.reconciliation import reconcile_all
from xp_core.logging import get_logger
from xp_core.models.entities import (
    Approval,
    Artifact,
    AuditEvent,
    AutomationRun,
    ConnectedService,
    EmailDraft,
    Notification,
    PaymentIntent,
    ResearchSource,
    ScheduledJob,
    ServiceCredential,
    Session,
    Task,
    TaskEvent,
    TaskStep,
    TelegramAccount,
    User,
    Wallet,
    WalletAddress,
    WalletTransaction,
    XpAccount,
    XpLedgerEntry,
)
from xp_core.services.storage import LocalStorage

log = get_logger(__name__)

ERASED_ON_CLOSURE = "[erased on account closure]"

RETAINED_SURFACES = [
    "xp_ledger_entries",
    "payment_intents",
    "xp_accounts",
    "task_events",
    "audit_events",
]

CLOSURE_DISCLOSURES = [
    "Your XP ledger entries, payment intents, XP account, task events, and "
    "audit events are retained: they are the immutable money and evidence "
    "trail, and they no longer contain your identity.",
    "Task and automation-job rows are kept as structural anchors with their "
    "content fields scrubbed, so retained evidence stays resolvable.",
    "Self-custody notice: erasing server-side wallet state does not move or "
    "affect your bitcoin - your recovery phrase remains the only control "
    "over your funds.",
    "This action is permanent; the account cannot be restored.",
]


class ClosureBlocked(Exception):
    """Closure preconditions unmet; carries precise, honest reasons."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


async def _count(session: AsyncSession, model: Any, *where: Any) -> int:
    stmt = select(func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return int((await session.execute(stmt)).scalar_one())


async def export_user_data(session: AsyncSession, user: User) -> dict[str, Any]:
    """Full JSON export of the caller's data; secrets are never included."""
    user_id = user.id
    wallets = (
        (await session.execute(select(Wallet).where(Wallet.user_id == user_id)))
        .scalars()
        .all()
    )
    wallet_ids = [w.id for w in wallets]
    transactions: list[WalletTransaction] = []
    if wallet_ids:
        transactions = (
            (
                await session.execute(
                    select(WalletTransaction).where(
                        WalletTransaction.wallet_id.in_(wallet_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
    tasks = (
        (await session.execute(select(Task).where(Task.user_id == user_id)))
        .scalars()
        .all()
    )
    task_ids = [t.id for t in tasks]

    def _dump(rows: list[Any], skip: set[str] = frozenset()) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            item = {
                c.name: getattr(row, c.name)
                for c in row.__table__.columns
                if c.name not in skip
            }
            for key, value in item.items():
                if isinstance(value, datetime):
                    item[key] = value.isoformat()
            out.append(item)
        return out

    sections: dict[str, Any] = {
        "profile": _dump([user], skip={"id"}),
        "telegram_accounts": _dump(
            (
                await session.execute(
                    select(TelegramAccount).where(TelegramAccount.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "sessions": _dump(
            (
                await session.execute(select(Session).where(Session.user_id == user_id))
            )
            .scalars()
            .all(),
            skip={"user_id", "token_hash"},
        ),
        "wallets": _dump(wallets, skip={"user_id"}),
        "wallet_addresses": _dump(
            (
                await session.execute(
                    select(WalletAddress).where(WalletAddress.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "wallet_transactions": _dump(transactions),
        "payment_intents": _dump(
            (
                await session.execute(
                    select(PaymentIntent).where(PaymentIntent.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "xp_account": _dump(
            (
                await session.execute(
                    select(XpAccount).where(XpAccount.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "xp_ledger_entries": _dump(
            (
                await session.execute(
                    select(XpLedgerEntry).where(XpLedgerEntry.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "tasks": _dump(tasks, skip={"user_id"}),
        "approvals": _dump(
            (
                await session.execute(
                    select(Approval).where(Approval.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "artifacts": _dump(
            (
                await session.execute(
                    select(Artifact).where(Artifact.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "scheduled_jobs": _dump(
            (
                await session.execute(
                    select(ScheduledJob).where(ScheduledJob.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "automation_runs": _dump(
            (
                await session.execute(
                    select(AutomationRun).where(AutomationRun.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "notifications": _dump(
            (
                await session.execute(
                    select(Notification).where(Notification.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "connected_services": _dump(
            (
                await session.execute(
                    select(ConnectedService).where(ConnectedService.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
        "email_drafts": _dump(
            (
                await session.execute(
                    select(EmailDraft).where(EmailDraft.user_id == user_id)
                )
            )
            .scalars()
            .all(),
            skip={"user_id"},
        ),
    }

    if task_ids:
        sections["task_steps"] = _dump(
            (
                await session.execute(
                    select(TaskStep).where(TaskStep.task_id.in_(task_ids))
                )
            )
            .scalars()
            .all()
        )
        sections["task_events"] = _dump(
            (
                await session.execute(
                    select(TaskEvent).where(TaskEvent.task_id.in_(task_ids))
                )
            )
            .scalars()
            .all()
        )
        sections["research_sources"] = _dump(
            (
                await session.execute(
                    select(ResearchSource).where(ResearchSource.task_id.in_(task_ids))
                )
            )
            .scalars()
            .all()
        )
    else:
        sections["task_steps"] = []
        sections["task_events"] = []
        sections["research_sources"] = []

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "sections": sections,
        "disclosures": [
            "Session token hashes are authentication material and are not exported.",
            "Connected-service credentials are encrypted at rest and their "
            "ciphertext is never exported.",
            "This export reflects the database at generation time.",
        ],
    }


async def close_account(
    session: AsyncSession,
    user: User,
    settings: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ledger-aware self-serve closure. Raises ClosureBlocked when unclean."""
    now = now or datetime.now(UTC)
    user_id = user.id

    reasons: list[str] = []
    running_tasks = await _count(session, Task, Task.user_id == user_id, Task.status == "running")
    if running_tasks:
        reasons.append(
            f"{running_tasks} task(s) still running - wait for them to finish or cancel them"
        )
    pending_approvals = await _count(
        session, Approval, Approval.user_id == user_id, Approval.status == "pending"
    )
    if pending_approvals:
        reasons.append(
            f"{pending_approvals} approval(s) pending a decision - resolve or let them expire"
        )
    money_in_motion = await _count(
        session,
        PaymentIntent,
        PaymentIntent.user_id == user_id,
        PaymentIntent.status.in_(
            ["created", "pending", "prepared", "authorized", "in_flight"]
        ),
    )
    if money_in_motion:
        reasons.append(
            f"{money_in_motion} payment intent(s) still open - let them settle or expire first"
        )
    balance = (
        await session.execute(
            select(XpAccount.balance).where(XpAccount.user_id == user_id)
        )
    ).scalar_one_or_none()
    if balance is not None and balance > 0:
        reasons.append(
            f"XP balance is {balance} - spend it down first; closure never "
            "fabricates a forfeit entry, and operator-assisted refund is the "
            "honest path for the remainder"
        )
    if user.status == "closed":
        reasons.append("account is already closed")
    if reasons:
        raise ClosureBlocked(reasons)

    report = await reconcile_all(session)
    if not report.get("ok") or report.get("discrepancies"):
        raise ClosureBlocked(
            [
                "ledger reconciliation is not clean - closure requires "
                "balance == sum(ledger entries) before any erasure"
            ]
        )

    erased: dict[str, int] = {}
    anonymized: dict[str, int] = {}

    wallet_ids = (
        await session.execute(select(Wallet.id).where(Wallet.user_id == user_id))
    ).scalars().all()
    artifact_keys = (
        await session.execute(
            select(Artifact.object_key).where(Artifact.user_id == user_id)
        )
    ).scalars().all()
    task_ids = (
        await session.execute(select(Task.id).where(Task.user_id == user_id))
    ).scalars().all()
    connection_ids = (
        await session.execute(
            select(ConnectedService.id).where(ConnectedService.user_id == user_id)
        )
    ).scalars().all()

    async def _erase(model: Any, *where: Any) -> int:
        result = await session.execute(delete(model).where(*where))
        return int(result.rowcount or 0)

    # user content and auth surfaces - hard delete
    erased["sessions"] = await _erase(Session, Session.user_id == user_id)
    erased["notifications"] = await _erase(Notification, Notification.user_id == user_id)
    erased["email_drafts"] = await _erase(EmailDraft, EmailDraft.user_id == user_id)
    if connection_ids:
        erased["service_credentials"] = await _erase(
            ServiceCredential, ServiceCredential.connection_id.in_(connection_ids)
        )
    erased["connected_services"] = await _erase(
        ConnectedService, ConnectedService.user_id == user_id
    )
    erased["approvals"] = await _erase(Approval, Approval.user_id == user_id)
    erased["automation_runs"] = await _erase(AutomationRun, AutomationRun.user_id == user_id)
    if task_ids:
        erased["research_sources"] = await _erase(
            ResearchSource, ResearchSource.task_id.in_(task_ids)
        )
        erased["task_steps"] = await _erase(TaskStep, TaskStep.task_id.in_(task_ids))
    erased["artifacts"] = await _erase(Artifact, Artifact.user_id == user_id)
    if wallet_ids:
        erased["wallet_transactions"] = await _erase(
            WalletTransaction, WalletTransaction.wallet_id.in_(wallet_ids)
        )
        erased["wallet_addresses"] = await _erase(
            WalletAddress, WalletAddress.user_id == user_id
        )
    erased["wallets"] = await _erase(Wallet, Wallet.user_id == user_id)

    # artifact files (explicit user action; the sweep can never do this)
    if artifact_keys:
        storage = LocalStorage(settings.artifact_dir)
        files_removed = 0
        for key in artifact_keys:
            if storage.exists(key):
                storage.delete(key)
                files_removed += 1
        erased["artifact_files"] = files_removed

    # content-bearing fields of structural rows are scrubbed in place
    scrubbed_tasks = await session.execute(
        update(Task)
        .where(Task.user_id == user_id)
        .values(objective=ERASED_ON_CLOSURE, deliverable=None, error=None)
    )
    anonymized["tasks_content_scrubbed"] = int(scrubbed_tasks.rowcount or 0)
    cancelled_jobs = await session.execute(
        update(ScheduledJob)
        .where(ScheduledJob.user_id == user_id, ScheduledJob.status != "cancelled")
        .values(
            status="cancelled",
            task_template={"objective": ERASED_ON_CLOSURE},
            conditions=None,
            next_run_at=None,
        )
    )
    anonymized["scheduled_jobs_cancelled"] = int(cancelled_jobs.rowcount or 0)

    # identity rows: unlink telegram, drop the display name, close the account
    erased["telegram_accounts"] = await _erase(
        TelegramAccount, TelegramAccount.user_id == user_id
    )
    await session.execute(
        update(User).where(User.id == user_id).values(display_name=None, status="closed")
    )
    anonymized["user_identity"] = 1

    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user_id,
            event_type="account.closed",
            resource_type="user",
            resource_id=user_id,
            metadata_redacted={
                "erased": erased,
                "anonymized": anonymized,
                "at": now.isoformat(),
            },
        )
    )
    await session.commit()
    log.info("account_closed", user_id=user_id, **erased)
    return {
        "status": "closed",
        "closed_at": now.isoformat(),
        "erased": erased,
        "anonymized": anonymized,
        "retained": RETAINED_SURFACES,
        "disclosures": CLOSURE_DISCLOSURES,
    }
