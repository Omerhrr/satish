"""Agent task lifecycle (phases 5+6): estimate, create (with budget
reservation), list, get, increase-budget, settle, cancel.

The full DSH plan/execute loop lands with the agent runtime integration;
this router establishes the durable task records, budget reservation and
cap flows, and explicit state machine (api_rules: explicit state values).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from xp_core.models.entities import Approval, AuditEvent, Task, TaskStep
from xp_core.pricing import estimate_task_cost_xp
from xp_core.schemas.api import (
    ApprovalDecisionIn,
    ApprovalOut,
    IncreaseBudgetIn,
    SettleTaskIn,
    TaskCreateIn,
    TaskEstimateOut,
    TaskEventOut,
    TaskEventPageOut,
    TaskOut,
    TaskResultOut,
)
from xp_core.services import ledger

from app.deps import CurrentUser, DbSession
from app.services import task_service

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


@router.post("/estimate", response_model=TaskEstimateOut)
async def estimate(payload: TaskCreateIn) -> TaskEstimateOut:
    """Pre-task estimate: deterministic heuristic + variable-cost disclosure
    (pricing_requirements #2/#3). The agent plan finalizes the estimate."""
    return TaskEstimateOut(**estimate_task_cost_xp(payload.objective))


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
    task = await task_service.get_owned_task(session, user.id, task_id)
    return _task_out(task)


@router.post("/{task_id}/increase-budget", response_model=TaskOut)
async def increase_budget(
    task_id: str, payload: IncreaseBudgetIn, user: CurrentUser, session: DbSession
) -> TaskOut:
    """User-authorized budget increase (acceptance #6: exceeding the approved
    budget requires ADDITIONAL authorization — this endpoint is that
    authorization, and only the user can call it; the agent registry has no
    path here)."""
    task = await task_service.increase_budget(
        session, user_id=user.id, task_id=task_id, additional_xp=payload.additional_xp
    )
    return _task_out(task)


@router.post("/{task_id}/settle", response_model=TaskOut)
async def settle_task(
    task_id: str, payload: SettleTaskIn, user: CurrentUser, session: DbSession
) -> TaskOut:
    """System seam: settle a finished task (charge within the cap, release
    the unused hold). The agent worker calls the service directly; this HTTP
    surface exists for ops/tests."""
    task = await task_service.settle_task_usage(
        session, user_id=user.id, task_id=task_id, actual_xp=payload.actual_xp
    )
    return _task_out(task)


@router.get("/{task_id}/result", response_model=TaskResultOut)
async def task_result(task_id: str, user: CurrentUser, session: DbSession) -> TaskResultOut:
    """Explicit result for a finished task (phase-7 acceptance #4): the
    deliverable, validated artifacts, source provenance, conflicts and gaps,
    limitations, and the XP receipt from the ledger trail."""
    result: TaskResultOut = await task_service.build_task_result(
        session, user_id=user.id, task_id=task_id
    )
    return result


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: str, user: CurrentUser, session: DbSession) -> TaskOut:
    """Cancel a task; the worker notices the durable flag between steps."""
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
    from app.services.agent_service import append_event

    await append_event(session, task.id, "task.cancelled", {"by": "user"})
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


# -- agent runtime (phase 6) ------------------------------------------------------------


@router.post("/{task_id}/run", response_model=TaskOut, status_code=status.HTTP_202_ACCEPTED)
async def run_task(task_id: str, user: CurrentUser, session: DbSession) -> TaskOut:
    """Start (or resume) the DSH run for this task.

    202 with the task in ``running`` (inline dev executes synchronously and
    the response already reflects the terminal state). Reservation must
    still be held; a fresh run is rejected when one is already in flight.
    """
    task = await task_service.get_owned_task(session, user.id, task_id)
    if task.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="task already running")
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"task already {task.status}"
        )
    if task.reserved_xp <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="budget reservation missing; recreate the task or increase the budget",
        )
    resume = task.status == "awaiting_approval"
    task.status = "running"
    await session.commit()

    from app.worker_bridge import enqueue_agent_task_job

    await enqueue_agent_task_job(task_id=task.id, resume=resume)
    await session.refresh(task)
    return _task_out(task)


@router.get("/{task_id}/events", response_model=TaskEventPageOut)
async def task_events(task_id: str, user: CurrentUser, session: DbSession) -> TaskEventPageOut:
    """The durable event stream: plan, steps, approvals, evaluation, outcome."""
    task = await task_service.get_owned_task(session, user.id, task_id)
    from app.services.agent_service import load_events

    rows = await load_events(session, task.id)
    return TaskEventPageOut(
        task_id=task.id,
        status=task.status,
        events=[
            TaskEventOut(
                seq=e.seq, event_type=e.event_type, payload=e.payload or {}, created_at=e.created_at
            )
            for e in rows
        ],
    )


@router.get("/{task_id}/steps", response_model=list[dict])
async def task_steps(task_id: str, user: CurrentUser, session: DbSession) -> list[dict]:
    task = await task_service.get_owned_task(session, user.id, task_id)
    rows = await session.execute(
        select(TaskStep)
        .where(TaskStep.task_id == task.id)
        .order_by(TaskStep.step_index)
    )
    return [
        {
            "step_index": s.step_index,
            "tool_name": s.tool_name,
            "status": s.status,
            "started_at": s.started_at,
            "completed_at": s.completed_at,
        }
        for s in rows.scalars()
    ]


@router.get("/{task_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(task_id: str, user: CurrentUser, session: DbSession) -> list[ApprovalOut]:
    await task_service.get_owned_task(session, user.id, task_id)
    rows = await session.execute(
        select(Approval)
        .where(Approval.task_id == task_id)
        .order_by(Approval.created_at.desc())
        .limit(50)
    )
    return [
        ApprovalOut(
            id=a.id,
            task_id=a.task_id,
            action_type=a.action_type,
            action_digest=a.action_digest,
            status=a.status,
            created_at=a.created_at,
            expires_at=a.expires_at,
        )
        for a in rows.scalars()
    ]


@router.post("/{task_id}/approvals/{approval_id}/decision", response_model=ApprovalOut)
async def decide_approval(
    task_id: str,
    approval_id: str,
    payload: ApprovalDecisionIn,
    user: CurrentUser,
    session: DbSession,
) -> ApprovalOut:
    """The USER approves or denies a tool action the runner paused on.

    The decision is bound to the approval's action digest; the runner will
    re-check this row on resume (the model has no path here).
    """
    task = await task_service.get_owned_task(session, user.id, task_id)
    approval = (
        await session.execute(
            select(Approval).where(Approval.id == approval_id, Approval.task_id == task.id)
        )
    ).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval not found")
    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"approval already {approval.status}"
        )
    approval.status = "approved" if payload.approve else "denied"
    approval.approved_at = datetime.now(UTC) if payload.approve else None
    approval.revoked_at = None if payload.approve else datetime.now(UTC)
    from app.services.agent_service import append_event

    await append_event(
        session,
        task.id,
        f"approval.{'approved' if payload.approve else 'denied'}",
        {"approval_id": approval.id, "tool": approval.action_type, "digest": approval.action_digest},
    )
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type=f"approval.{approval.status}",
            resource_type="approval",
            resource_id=approval.id,
            metadata_redacted={"task_id": task.id, "action_type": approval.action_type},
        )
    )
    await session.commit()
    await session.refresh(approval)
    return ApprovalOut(
        id=approval.id,
        task_id=approval.task_id,
        action_type=approval.action_type,
        action_digest=approval.action_digest,
        status=approval.status,
        created_at=approval.created_at,
        expires_at=approval.expires_at,
    )
