"""Task budget lifecycle service (phase 5 acceptance #6 + task_charge_flow).

Rules implemented here, all deterministic backend code:

- Charge cap: actual usage can never exceed the approved budget. The ledger
  raises before any entry lands if it would (acceptance #6: "A task cannot
  exceed its approved XP budget without additional authorization").
- Additional authorization: raising a budget is a USER action through
  POST /tasks/{id}/increase-budget — it reserves the delta atomically with
  its own idempotency key and appends an audit event. The agent registry has
  no tool that reaches this function (proven by test), so the agent cannot
  grant itself more budget.
- Failed-task rule: a failed task releases its FULL unused reservation —
  the user is not charged for work the platform failed to deliver
  (pricing_requirements #6: clear failed-task rules). The release is an
  auditable reservation_release entry, never a history rewrite.
- Cancellation rule: same full release, marked cancelled.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.logging import get_logger
from xp_core.models.entities import AuditEvent, Task
from xp_core.services import ledger

log = get_logger(__name__)


async def get_owned_task(session: AsyncSession, user_id: str, task_id: str) -> Task:
    task = (
        await session.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


async def increase_budget(
    session: AsyncSession, *, user_id: str, task_id: str, additional_xp: int
) -> Task:
    """User-authorized budget increase: reserve the delta, raise the cap.

    Idempotency key binds (task, resulting total) so a retried request with
    the same target total replays harmlessly, while a second, deliberate
    increase gets a fresh key.
    """
    if additional_xp <= 0:
        raise ValueError("additional_xp must be positive")
    task = await get_owned_task(session, user_id, task_id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409, detail=f"cannot increase budget on a {task.status} task"
        )
    new_total = task.budget_xp + additional_xp
    try:
        await ledger.reserve_budget(
            session,
            user_id=user_id,
            task_id=task_id,
            amount=additional_xp,
            idempotency_key=f"reserve:inc:{task_id}:{new_total}",
        )
    except ledger.LedgerError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=402, detail=f"budget increase failed: {exc}"
        ) from exc
    task.budget_xp = new_total
    task.reserved_xp = new_total
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user_id,
            event_type="task.budget_increased",
            resource_type="task",
            resource_id=task_id,
            metadata_redacted={
                "additional_xp": additional_xp,
                "new_budget_xp": new_total,
            },
        )
    )
    await session.commit()
    await session.refresh(task)
    return task


async def settle_task_usage(
    session: AsyncSession, *, user_id: str, task_id: str, actual_xp: int
) -> Task:
    """Settle a task: charge actual usage within the cap, release the unused hold.

    Called by the worker at the end of a run (phase 6) and exposed as a
    system seam for tests/ops. actual_xp > budget_xp is refused by the
    ledger BEFORE anything is written — the approved cap is a hard ceiling.
    """
    task = await get_owned_task(session, user_id, task_id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"task already {task.status}")
    if actual_xp > task.budget_xp:
        raise HTTPException(
            status_code=409,
            detail=(
                f"actual_xp {actual_xp} exceeds the approved budget {task.budget_xp}; "
                "increase the budget first (user authorization required)"
            ),
        )
    try:
        await ledger.settle_task(
            session,
            user_id=user_id,
            task_id=task_id,
            reserved_xp=task.reserved_xp,
            actual_xp=actual_xp,
        )
    except ledger.LedgerError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"settlement refused: {exc}") from exc
    task.reserved_xp = 0
    task.actual_xp = actual_xp
    task.status = "completed"
    task.completed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor_type="system",
            event_type="task.settled",
            resource_type="task",
            resource_id=task_id,
            metadata_redacted={"actual_xp": actual_xp, "budget_xp": task.budget_xp},
        )
    )
    await session.commit()
    await session.refresh(task)
    log.info("task_settled", task_id=task_id, actual_xp=actual_xp)
    return task


async def fail_task(session: AsyncSession, *, user_id: str, task_id: str, reason: str) -> Task:
    """Failed-task rule: release the full unused reservation; charge nothing."""
    task = await get_owned_task(session, user_id, task_id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"task already {task.status}")
    released = task.reserved_xp
    if released > 0:
        await ledger.release_reservation(
            session, user_id=user_id, task_id=task_id, amount=released
        )
        task.reserved_xp = 0
    task.status = "failed"
    task.error = reason[:2000] if reason else None
    task.completed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor_type="system",
            event_type="task.failed",
            resource_type="task",
            resource_id=task_id,
            metadata_redacted={"released_xp": released, "reason": (reason or "")[:500]},
        )
    )
    await session.commit()
    await session.refresh(task)
    log.info("task_failed_released", task_id=task_id, released=released)
    return task


__all__ = ["fail_task", "get_owned_task", "increase_budget", "settle_task_usage"]
