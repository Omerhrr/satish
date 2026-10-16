"""Automation jobs (phase 9): create, inspect, pause, resume, cancel, run.

Deliverables: "Scheduled jobs", "Pause, resume, cancel, and failure
handling", "Automation run history". Budget enforcement lives in
xp_core.services.automation (per-run cap, total cap, deterministic
reservation keys) - this router only validates ownership and state.

Direct user creation needs NO approval (the user is the actor); only the
agent-initiated automation.schedule tool passes the approval gate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import AuditEvent, AutomationRun, ScheduledJob
from xp_core.schemas.api import (
    AutomationRunOut,
    JobCreateIn,
    JobOut,
)
from xp_core.services import automation as automation_core

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/jobs", tags=["automation"])


def _job_out(job: ScheduledJob) -> JobOut:
    template = job.task_template or {}
    return JobOut(
        id=job.id,
        objective=str(template.get("objective", "")),
        schedule=job.schedule,
        next_run_at=job.next_run_at,
        last_run_at=job.last_run_at,
        last_run_status=job.last_run_status,
        status=job.status,
        budget_per_run_xp=job.budget_per_run_xp,
        budget_total_xp=job.budget_total_xp,
        total_spent_xp=job.total_spent_xp,
        run_count=job.run_count,
        consecutive_failures=job.consecutive_failures,
        auto_paused_reason=job.auto_paused_reason,
        conditions=job.conditions,
        created_at=job.created_at,
    )


def _run_out(run: AutomationRun) -> AutomationRunOut:
    return AutomationRunOut(
        id=run.id,
        job_id=run.job_id,
        run_number=run.run_number,
        trigger=run.trigger,
        status=run.status,
        task_id=run.task_id,
        xp_charged=run.xp_charged,
        xp_budget_per_run=run.xp_budget_per_run,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def get_owned_job(session, user_id: str, job_id: str) -> ScheduledJob:
    job = (
        await session.execute(
            select(ScheduledJob).where(
                ScheduledJob.id == job_id, ScheduledJob.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
        )
    return job


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreateIn, user: CurrentUser, session: DbSession
) -> JobOut:
    settings = get_settings()
    try:
        job, _disclosure = await automation_core.create_job(
            session,
            user_id=user.id,
            objective=payload.objective,
            schedule=payload.schedule,
            budget_per_run_xp=payload.budget_per_run_xp,
            budget_total_xp=payload.budget_total_xp,
            conditions=payload.conditions,
            settings=settings,
        )
    except (automation_core.ScheduleError, automation_core.JobValidationError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type="job.created",
            resource_type="scheduled_job",
            resource_id=job.id,
            metadata_redacted={
                "schedule": job.schedule,
                "budget_per_run_xp": job.budget_per_run_xp,
                "budget_total_xp": job.budget_total_xp,
            },
        )
    )
    await session.commit()
    await session.refresh(job)
    return _job_out(job)


@router.get("", response_model=list[JobOut])
async def list_jobs(user: CurrentUser, session: DbSession) -> list[JobOut]:
    rows = (
        (
            await session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.user_id == user.id)
                .order_by(ScheduledJob.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_job_out(row) for row in rows]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, user: CurrentUser, session: DbSession) -> JobOut:
    job = await get_owned_job(session, user.id, job_id)
    return _job_out(job)


@router.get("/{job_id}/runs", response_model=list[AutomationRunOut])
async def list_runs(
    job_id: str, user: CurrentUser, session: DbSession
) -> list[AutomationRunOut]:
    await get_owned_job(session, user.id, job_id)
    rows = (
        (
            await session.execute(
                select(AutomationRun)
                .where(AutomationRun.job_id == job_id)
                .order_by(AutomationRun.run_number.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_run_out(row) for row in rows]


@router.post("/{job_id}/pause", response_model=JobOut)
async def pause_job(job_id: str, user: CurrentUser, session: DbSession) -> JobOut:
    job = await get_owned_job(session, user.id, job_id)
    if job.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job is {job.status}, not active",
        )
    job.status = "paused"
    job.auto_paused_reason = None  # user-intent pause, not a failure pause
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type="job.paused",
            resource_type="scheduled_job",
            resource_id=job.id,
            metadata_redacted={},
        )
    )
    await session.commit()
    await session.refresh(job)
    return _job_out(job)


@router.post("/{job_id}/resume", response_model=JobOut)
async def resume_job(job_id: str, user: CurrentUser, session: DbSession) -> JobOut:
    job = await get_owned_job(session, user.id, job_id)
    if job.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job is {job.status}, not paused",
        )
    job.status = "active"
    job.auto_paused_reason = None
    job.consecutive_failures = 0  # explicit human decision resets the failure ladder
    job.next_run_at = automation_core.next_run_after(
        job.schedule, datetime.now(UTC).replace(tzinfo=None)
    )
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type="job.resumed",
            resource_type="scheduled_job",
            resource_id=job.id,
            metadata_redacted={},
        )
    )
    await session.commit()
    await session.refresh(job)
    return _job_out(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: str, user: CurrentUser, session: DbSession) -> JobOut:
    job = await get_owned_job(session, user.id, job_id)
    if job.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="job already cancelled"
        )
    job.status = "cancelled"
    job.next_run_at = None
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.id,
            event_type="job.cancelled",
            resource_type="scheduled_job",
            resource_id=job.id,
            metadata_redacted={},
        )
    )
    await session.commit()
    await session.refresh(job)
    return _job_out(job)


@router.post("/{job_id}/run", response_model=AutomationRunOut)
async def trigger_run(
    job_id: str, user: CurrentUser, session: DbSession
) -> AutomationRunOut:
    """Manual one-shot trigger. Budgets, approval-wait, and failure policy
    are the SAME code path as the scheduled sweep (process_job) - a manual
    run is never a bypass. Paused jobs may be triggered deliberately;
    cancelled jobs may not."""
    from xp_core.db import get_session_factory

    job = await get_owned_job(session, user.id, job_id)
    if job.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="job is cancelled"
        )
    settings = get_settings()
    factory = get_session_factory()

    async def _execute(factory_, task_id, settings_, resume: bool = False):
        from app.services.agent_service import run_agent_task

        return await run_agent_task(factory_, task_id, settings_, resume=resume)

    try:
        run = await automation_core.process_job(
            session,
            job,
            settings,
            session_factory=factory,
            execute_task=_execute,
            trigger="manual",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # executor surfaced an error; the run row has it
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"automation run failed: {exc}",
        ) from exc
    return _run_out(run)
