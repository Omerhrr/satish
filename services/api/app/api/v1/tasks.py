"""Agent task lifecycle: create (with budget reservation), list, get, cancel.

The full DSH plan/execute loop lands with the agent adapter integration; this
router establishes the durable task records, budget reservation flow, and
explicit state machine (api_rules: explicit state values).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from xp_core.models.entities import AuditEvent, Task
from xp_core.schemas.api import TaskCreateIn, TaskOut
from xp_core.services import ledger

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_out(t: Task) -> TaskOut:
    return TaskOut(
        id=t.id,
        objective=t.objective,
        status=t.status,
        budget_xp=t.budget_xp,
        reserved_xp=t.reserved_xp,
        actual_xp=t.actual_xp,
        deliverable=t.deliverable,
        created_at=t.created_at,
        started_at=t.started_at,
        completed_at=t.completed_at,
        cancelled_at=t.cancelled_at,
    )


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreateIn, user: CurrentUser, session: DbSession) -> TaskOut:
    """Create a task and atomically reserve its XP budget (task_charge_flow #2-3)."""
    task = Task(
        user_id=user.id,
        objective=payload.objective,
        status="planned",
        budget_xp=payload.budget_xp,
    )
    session.add(task)
    await session.flush()
    try:
        await ledger.reserve_budget(
            session,
            user_id=user.id,
            task_id=task.id,
            amount=payload.budget_xp,
            idempotency_key=payload.idempotency_key,
        )
    except ledger.LedgerError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"budget reservation failed: {exc}",
        ) from exc
    task.reserved_xp = payload.budget_xp
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type="task.created",
            resource_type="task",
            resource_id=task.id,
            metadata_redacted={"budget_xp": payload.budget_xp},
        )
    )
    await session.commit()
    await session.refresh(task)
    return _task_out(task)


@router.get("", response_model=list[TaskOut])
async def list_tasks(user: CurrentUser, session: DbSession) -> list[TaskOut]:
    rows = await session.execute(
        select(Task)
        .where(Task.user_id == user.id)
        .order_by(Task.created_at.desc())
        .limit(100)
    )
    return [_task_out(t) for t in rows.scalars()]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, user: CurrentUser, session: DbSession) -> TaskOut:
    task = (
        await session.execute(
            select(Task).where(Task.id == task_id, Task.user_id == user.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return _task_out(task)


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: str, user: CurrentUser, session: DbSession) -> TaskOut:
    """Cancel a task and release any unused reservation."""
    task = (
        await session.execute(
            select(Task).where(Task.id == task_id, Task.user_id == user.id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"task already {task.status}"
        )
    if task.reserved_xp > 0:
        await ledger.release_reservation(
            session, user_id=user.id, task_id=task.id, amount=task.reserved_xp
        )
        task.reserved_xp = 0
    task.status = "cancelled"
    task.cancelled_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type="task.cancelled",
            resource_type="task",
            resource_id=task.id,
            metadata_redacted=None,
        )
    )
    await session.commit()
    await session.refresh(task)
    return _task_out(task)
