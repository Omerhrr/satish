"""Automation scheduler core (phase 9).

Deliverables: "Scheduled jobs", "Condition-based notifications", "Pause,
resume, cancel, and failure handling", "Automation run history", plus the
TK-limit acceptance: "Recurring jobs enforce per-run TK limits and total
limits where configured" and "Failed jobs do not silently repeat
consequential actions".

Design rules (all enforced in THIS module, never by the model):
- Deterministic schedule grammar (see parse_schedule): every N minutes/
  hours/days, daily/weekly/monthly at one or more times, optional time zone.
  Anything else is a loud refusal.
- Every attempt is recorded as an ``AutomationRun`` row - success, failure,
  or skip, always with its reason.
- Budget: each run's task budget is ``min(budget_per_run_xp, remaining
  total)``; the ledger refuses settlement beyond a task budget, so the cap
  holds end-to-end. Total exhausted -> run skipped AND job auto-paused.
- Failures: consecutive failures auto-pause the job and notify the user.
- Approval-blocked runs (the spawned task needs a user decision) WAIT: the
  sweep neither re-runs the job nor re-requests approval while one is
  pending - consequential actions are never silently repeated. A denied
  approval fails the task explicitly; an approved one resumes it.
- xp_core stays transport-agnostic: the executor callable is injected (the
  worker passes the agent runner; tests pass their own).
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import (
    Approval,
    AutomationRun,
    Notification,
    ScheduledJob,
    Task,
    XpAccount,
)
from xp_core.services import ledger

log = get_logger(__name__)


class ScheduleError(ValueError):
    """Raised for any schedule expression outside the published grammar."""


class JobValidationError(ValueError):
    """Raised for invalid budgets/conditions on job creation."""


Every = re.compile(r"^every (\d+)\s*([smhd])$")
_TIMES = r"(\d{1,2}:\d{2}(?:\s*,\s*\d{1,2}:\d{2})*)"
Daily = re.compile(rf"^daily {_TIMES}$")
Weekly = re.compile(rf"^weekly ([a-z]{{3}}(?:\s*,\s*[a-z]{{3}})*) {_TIMES}$")
Monthly = re.compile(rf"^monthly (\d{{1,2}}) {_TIMES}$")
_TZ = re.compile(r"\s+tz\s+([A-Za-z_]+(?:/[A-Za-z_+\-0-9]+){0,2})$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(slots=True)
class Schedule:
    expr: str
    kind: str  # every | daily | weekly | monthly
    seconds: int | None = None
    hour: int | None = None
    minute: int | None = None
    times: list[tuple[int, int]] | None = None
    weekdays: list[int] | None = None
    day_of_month: int | None = None
    tz: str = "UTC"


def _times(text: str) -> list[tuple[int, int]]:
    out = []
    for part in text.split(","):
        h, m = (int(x) for x in part.strip().split(":"))
        if h > 23 or m > 59:
            raise ScheduleError("times must be valid HH:MM")
        out.append((h, m))
    if len(out) > 24:
        raise ScheduleError("at most 24 times a day")
    return sorted(set(out))


def parse_schedule(expr: str) -> Schedule:
    """Parse the published schedule grammar. Anything else raises ScheduleError.

    every <n><s|m|h|d>             (>= 60s)        every 15m, every 2h
    daily HH:MM[,HH:MM...]                          daily 08:00,18:30
    weekly mon[,tue...] HH:MM[,...]                 weekly mon,fri 09:00
    monthly <day 1-28> HH:MM[,...]                  monthly 1 07:00
    aliases: hourly, daily. Any of the timed forms may end with
    ``tz Area/City`` (default UTC), e.g. ``daily 08:00 tz Africa/Lagos``.
    """
    raw = (expr or "").strip()
    tz = "UTC"
    tzm = _TZ.search(raw)
    if tzm:
        tz = tzm.group(1)
        raw = raw[: tzm.start()]
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz)
        except Exception as exc:
            raise ScheduleError(f"unknown time zone {tz!r}") from exc
    text = " ".join(raw.lower().split())
    suffix = f" tz {tz}" if tzm else ""
    if text == "hourly":
        return Schedule(expr="hourly", kind="every", seconds=3600)
    if text == "daily":
        text = "daily 00:00"
    m = Every.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        seconds = n * _UNIT_SECONDS[unit]
        if seconds < 60:
            raise ScheduleError("minimum cadence is 60 seconds")
        return Schedule(expr=f"every {n}{unit}", kind="every", seconds=seconds)
    m = Daily.match(text)
    if m:
        times = _times(m.group(1))
        return Schedule(expr=text + suffix, kind="daily", hour=times[0][0], minute=times[0][1], times=times, tz=tz)
    m = Weekly.match(text)
    if m:
        names = [d.strip() for d in m.group(1).split(",")]
        if any(d not in _DAYS for d in names):
            raise ScheduleError("weekdays are mon tue wed thu fri sat sun")
        times = _times(m.group(2))
        return Schedule(expr=text + suffix, kind="weekly", times=times,
                        weekdays=sorted({_DAYS.index(d) for d in names}), tz=tz)
    m = Monthly.match(text)
    if m:
        day = int(m.group(1))
        if not 1 <= day <= 28:
            raise ScheduleError("monthly day must be 1-28")
        return Schedule(expr=text + suffix, kind="monthly", times=_times(m.group(2)), day_of_month=day, tz=tz)
    raise ScheduleError(
        "unsupported schedule; use 'every <n><m|h|d>' (>= 1 minute), 'daily HH:MM[,HH:MM]', "
        "'weekly mon,fri HH:MM', 'monthly <1-28> HH:MM' (optionally ending 'tz Africa/Lagos'), "
        "'hourly', or 'daily'"
    )


def next_run_after(expr: str, after: datetime) -> datetime:
    """Deterministic next fire time strictly after ``after`` (naive-UTC in, naive-UTC out)."""
    sched = parse_schedule(expr)
    if sched.kind == "every":
        assert sched.seconds is not None
        return after + timedelta(seconds=sched.seconds)
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(sched.tz)
    local_after = after.replace(tzinfo=UTC).astimezone(zone)
    for day_offset in range(0, 62):
        day = (local_after + timedelta(days=day_offset)).date()
        if sched.kind == "weekly" and day.weekday() not in (sched.weekdays or []):
            continue
        if sched.kind == "monthly" and day.day != sched.day_of_month:
            continue
        for h, m in sched.times or []:
            cand = datetime(day.year, day.month, day.day, h, m, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)
            if cand > after:
                return cand
    raise ScheduleError("schedule never fires")  # pragma: no cover


VALID_CONDITION_KEYS = {"notify_on", "balance_below_xp"}
VALID_NOTIFY_EVENTS = {"run_succeeded", "run_failed"}


def validate_conditions(conditions: dict[str, Any] | None) -> dict[str, Any] | None:
    """Whitelist-validated condition spec; unknown keys refuse (never ignored)."""
    if conditions is None:
        return None
    if not isinstance(conditions, dict):
        raise JobValidationError("conditions must be an object")
    unknown = set(conditions) - VALID_CONDITION_KEYS
    if unknown:
        raise JobValidationError(
            f"unknown condition keys: {', '.join(sorted(unknown))}"
        )
    cleaned: dict[str, Any] = {}
    if "notify_on" in conditions:
        events = conditions["notify_on"]
        if (
            not isinstance(events, list)
            or not events
            or not all(e in VALID_NOTIFY_EVENTS for e in events)
        ):
            raise JobValidationError(
                "notify_on must be a non-empty list of run_succeeded|run_failed"
            )
        cleaned["notify_on"] = sorted(set(events))
    if "balance_below_xp" in conditions:
        value = conditions["balance_below_xp"]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise JobValidationError("balance_below_xp must be a positive integer")
        cleaned["balance_below_xp"] = value
    return cleaned or None


def validate_budgets(
    settings: Settings,
    *,
    budget_per_run_xp: int,
    budget_total_xp: int | None,
) -> tuple[int, int | None]:
    """Clamp-to-refuse budget validation against operator caps."""
    if not isinstance(budget_per_run_xp, int) or budget_per_run_xp < 1:
        raise JobValidationError("budget_per_run_xp must be a positive integer")
    if budget_per_run_xp > settings.automation_max_budget_per_run_xp:
        raise JobValidationError(
            f"budget_per_run_xp exceeds operator cap "
            f"({settings.automation_max_budget_per_run_xp})"
        )
    if budget_total_xp is not None:
        if not isinstance(budget_total_xp, int) or budget_total_xp < budget_per_run_xp:
            raise JobValidationError(
                "budget_total_xp must be an integer >= budget_per_run_xp"
            )
        if budget_total_xp > settings.automation_max_budget_total_xp:
            raise JobValidationError(
                f"budget_total_xp exceeds operator cap "
                f"({settings.automation_max_budget_total_xp})"
            )
    return budget_per_run_xp, budget_total_xp


async def create_job(
    session: AsyncSession,
    *,
    user_id: str,
    objective: str,
    schedule: str,
    budget_per_run_xp: int,
    settings: Settings,
    budget_total_xp: int | None = None,
    conditions: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> tuple[ScheduledJob, str | None]:
    """Create a validated, active scheduled job. Returns (job, disclosure)."""
    if not (objective or "").strip():
        raise JobValidationError("objective is required")
    parse_schedule(schedule)
    per_run, total = validate_budgets(
        settings, budget_per_run_xp=budget_per_run_xp, budget_total_xp=budget_total_xp
    )
    cleaned_conditions = validate_conditions(conditions)
    now = now or datetime.now(UTC).replace(tzinfo=None)
    job = ScheduledJob(
        user_id=user_id,
        task_template={"objective": objective.strip()},
        schedule=schedule.strip().lower(),
        conditions=cleaned_conditions,
        budget_per_run_xp=per_run,
        budget_total_xp=total,
        status="active",
        next_run_at=next_run_after(schedule, now),
    )
    session.add(job)
    await session.flush()
    disclosure = None
    if conditions is not None and cleaned_conditions != conditions:
        disclosure = (
            "conditions normalized (duplicates removed / ordering canonicalized)"
        )
    log.info(
        "job_created",
        user_id=user_id,
        job_id=job.id,
        schedule=job.schedule,
        budget_per_run_xp=per_run,
        budget_total_xp=total,
    )
    return job, disclosure


Executor = Callable[..., Awaitable[dict[str, Any]]]

RUN_STATUSES = {
    "running",
    "succeeded",
    "failed",
    "blocked_on_approval",
    "skipped_budget",
    "skipped_total_budget",
    "skipped_cancelled",
}


async def create_notification(
    session: AsyncSession,
    *,
    user_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    job_id: str | None = None,
    run_id: str | None = None,
) -> Notification:
    row = Notification(
        user_id=user_id, kind=kind, payload=payload or {}, job_id=job_id, run_id=run_id
    )
    session.add(row)
    await session.flush()
    return row


async def _latest_run(session: AsyncSession, job_id: str) -> AutomationRun | None:
    return (
        await session.execute(
            select(AutomationRun)
            .where(AutomationRun.job_id == job_id)
            .order_by(AutomationRun.run_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _approval_state(session: AsyncSession, task_id: str) -> str:
    """pending | denied | approved | none - for the task's pending-flow approvals."""
    rows = (
        (
            await session.execute(
                select(Approval)
                .where(Approval.task_id == task_id)
                .order_by(Approval.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return "none"
    if any(r.status == "pending" for r in rows):
        return "pending"
    if any(r.status == "denied" for r in rows):
        return "denied"
    if any(r.status == "approved" for r in rows):
        return "approved"
    return "none"


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def _fail_task(session: AsyncSession, task: Task, *, reason: str) -> None:
    """Full release + failed status (same rules as the manual fail path)."""
    if task.reserved_xp:
        with contextlib.suppress(ledger.LedgerError):
            # Already-released reservations are caught by the reconciliation
            # sweep's double-check; never double-release here.
            await ledger.release_reservation(
                session,
                user_id=task.user_id,
                task_id=task.id,
                amount=task.reserved_xp,
                idempotency_key=f"fail:{task.id}",
            )
    task.reserved_xp = 0
    task.status = "failed"
    task.error = reason
    task.completed_at = datetime.now(UTC)


async def _finalize_run(
    session: AsyncSession,
    *,
    job: ScheduledJob,
    run: AutomationRun,
    task: Task | None,
    settings: Settings,
) -> None:
    """Bookkeep one finished execution: run row, counters, notifications, auto-pause."""
    run.finished_at = datetime.now(UTC)
    if task is not None and task.status == "completed":
        run.status = "succeeded"
        run.xp_charged = int(task.actual_xp or 0)
        job.consecutive_failures = 0
    elif task is not None and task.status == "awaiting_approval":
        run.status = "blocked_on_approval"
    elif task is not None and task.status == "cancelled":
        run.status = "skipped_cancelled"
        run.error = task.error or "task cancelled mid-run"
    else:
        run.status = "failed"
        run.error = (task.error if task is not None else None) or "run failed"
        job.consecutive_failures += 1

    # run_count is incremented when the run ROW is created (spawn paths);
    # finalization only records outcome + spend bookkeeping.
    job.last_run_at = run.started_at
    job.last_run_status = run.status
    job.total_spent_xp += run.xp_charged

    if (
        run.status == "failed"
        and job.status == "active"
        and job.consecutive_failures >= settings.automation_max_consecutive_failures
    ):
        job.status = "paused"
        job.auto_paused_reason = (
            f"consecutive_failures ({job.consecutive_failures} >= "
            f"{settings.automation_max_consecutive_failures})"
        )
        await create_notification(
            session,
            user_id=job.user_id,
            kind="automation.auto_paused",
            payload={
                "job_id": job.id,
                "reason": job.auto_paused_reason,
                "run_id": run.id,
            },
            job_id=job.id,
            run_id=run.id,
        )

    conditions = job.conditions or {}
    if run.status == "succeeded" and "run_succeeded" in conditions.get("notify_on", []):
        await create_notification(
            session,
            user_id=job.user_id,
            kind="automation.run_succeeded",
            payload={"job_id": job.id, "run_id": run.id, "task_id": run.task_id},
            job_id=job.id,
            run_id=run.id,
        )
    if run.status == "failed" and "run_failed" in conditions.get("notify_on", []):
        await create_notification(
            session,
            user_id=job.user_id,
            kind="automation.run_failed",
            payload={
                "job_id": job.id,
                "run_id": run.id,
                "task_id": run.task_id,
                "error": run.error,
            },
            job_id=job.id,
            run_id=run.id,
        )
    if "balance_below_xp" in conditions and run.status in {"succeeded", "failed"}:
        account = (
            await session.execute(
                select(XpAccount).where(XpAccount.user_id == job.user_id)
            )
        ).scalar_one_or_none()
        threshold = int(conditions["balance_below_xp"])
        if account is not None and account.balance < threshold:
            await create_notification(
                session,
                user_id=job.user_id,
                kind="automation.balance_below",
                payload={
                    "job_id": job.id,
                    "run_id": run.id,
                    "balance": int(account.balance),
                    "threshold": threshold,
                },
                job_id=job.id,
                run_id=run.id,
            )


async def process_job(
    session: AsyncSession,
    job: ScheduledJob,
    settings: Settings,
    *,
    session_factory,
    execute_task: Executor | None = None,
    trigger: str = "scheduled",
    now: datetime | None = None,
) -> AutomationRun:
    """Run one scheduling decision for a single job.

    The caller owns the transaction: this function commits at the safe
    boundaries (after task+run creation, and after finalization) so a worker
    crash can never double-charge - the run_number is unique per job and the
    reservation key is deterministic (``automation:{job_id}:{run_number}``).
    """
    now = _naive(now) or datetime.now(UTC)

    if execute_task is None:
        raise RuntimeError(
            "no automation executor configured (worker misconfiguration)"
        )

    # 1) A run still marked running: crash recovery. Stale -> failed + counted;
    #    fresh -> wait (never run the same job concurrently).
    last = await _latest_run(session, job.id)
    if last is not None and last.status == "running":
        started = _naive(last.started_at) or now
        if (now - started).total_seconds() < settings.automation_run_stale_seconds:
            log.warning("job_run_still_running_wait", job_id=job.id, run_id=last.id)
            return last
        last.status = "failed"
        last.error = "worker restart interrupted the run (marked stale)"
        last.finished_at = now
        job.consecutive_failures += 1
        job.last_run_status = "failed"
        if (
            job.status == "active"
            and job.consecutive_failures >= settings.automation_max_consecutive_failures
        ):
            job.status = "paused"
            job.auto_paused_reason = (
                f"consecutive_failures ({job.consecutive_failures} >= "
                f"{settings.automation_max_consecutive_failures})"
            )
        await session.commit()

    # 2) Approval-blocked continuation: WAIT, resume, or fail - never repeat.
    last = await _latest_run(session, job.id)
    if last is not None and last.status == "blocked_on_approval" and last.task_id:
        task = (
            await session.execute(select(Task).where(Task.id == last.task_id))
        ).scalar_one_or_none()
        state = await _approval_state(session, last.task_id)
        if state == "pending" or task is None:
            # Consequential actions are never silently repeated: the pending
            # approval is the visible state; the job simply waits.
            log.info("job_waits_for_approval", job_id=job.id, run_id=last.id)
            return last
        if state == "denied":
            if task is not None:
                await _fail_task(session, task, reason="approval denied by user")
            run = AutomationRun(
                job_id=job.id,
                user_id=job.user_id,
                run_number=job.run_count + 1,
                trigger=trigger,
                status="failed",
                task_id=last.task_id,
                xp_budget_per_run=job.budget_per_run_xp,
                error="approval denied by user",
                started_at=now,
                finished_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            job.last_run_status = "failed"
            job.consecutive_failures += 1
            job.run_count += 1
            await session.commit()
            return run
        # approved -> resume the SAME task (durable state does the rest)
        task.status = "running"
        await session.commit()
        await execute_task(session_factory, last.task_id, settings, resume=True)
        await session.refresh(task)
        await _finalize_run(session, job=job, run=last, task=task, settings=settings)
        await session.commit()
        return last

    # 3) Budget: per-run cap AND remaining total (where configured).
    remaining_total: int | None = None
    if job.budget_total_xp is not None:
        remaining_total = int(job.budget_total_xp) - int(job.total_spent_xp)
        if remaining_total <= 0:
            run = AutomationRun(
                job_id=job.id,
                user_id=job.user_id,
                run_number=job.run_count + 1,
                trigger=trigger,
                status="skipped_total_budget",
                xp_budget_per_run=job.budget_per_run_xp,
                error=(
                    f"total budget exhausted ({job.total_spent_xp}/{job.budget_total_xp} TK); "
                    "job auto-paused"
                ),
                started_at=now,
                finished_at=datetime.now(UTC),
            )
            session.add(run)
            job.status = "paused"
            job.auto_paused_reason = "budget_total_exhausted"
            job.run_count += 1
            job.last_run_status = "skipped_total_budget"
            await create_notification(
                session,
                user_id=job.user_id,
                kind="automation.auto_paused",
                payload={"job_id": job.id, "reason": job.auto_paused_reason},
                job_id=job.id,
            )
            await session.commit()
            return run

    budget = job.budget_per_run_xp
    if remaining_total is not None:
        budget = min(budget, remaining_total)

    # 4) Affordability pre-check: record the skip WITHOUT touching the
    #    ledger. The reserve below remains the atomic gate - this pre-check
    #    exists so the common "balance too low" case is a clean, fully
    #    committed skip row instead of an aborted reservation transaction.
    account = (
        await session.execute(select(XpAccount).where(XpAccount.user_id == job.user_id))
    ).scalar_one_or_none()
    if account is None or account.balance < budget:
        balance = int(account.balance) if account is not None else 0
        run = AutomationRun(
            job_id=job.id,
            user_id=job.user_id,
            run_number=job.run_count + 1,
            trigger=trigger,
            status="skipped_budget",
            xp_budget_per_run=budget,
            error=(
                f"insufficient TK balance ({balance} < {budget} required); "
                "job stays scheduled and will retry next sweep"
            ),
            started_at=now,
            finished_at=datetime.now(UTC),
        )
        session.add(run)
        job.run_count += 1
        job.last_run_status = "skipped_budget"
        job.last_run_at = now
        job.next_run_at = next_run_after(job.schedule, now)
        await session.commit()
        return run

    # 5) Spawn the task + run row atomically; deterministic reservation key.
    objective = str((job.task_template or {}).get("objective", "")).strip()
    task = Task(
        user_id=job.user_id,
        objective=objective,
        status="planned",
        budget_xp=budget,
    )
    session.add(task)
    await session.flush()
    run = AutomationRun(
        job_id=job.id,
        user_id=job.user_id,
        run_number=job.run_count + 1,
        trigger=trigger,
        status="running",
        task_id=task.id,
        xp_budget_per_run=budget,
        started_at=now,
    )
    session.add(run)
    await session.flush()
    try:
        await ledger.reserve_budget(
            session,
            user_id=job.user_id,
            task_id=task.id,
            amount=budget,
            idempotency_key=f"automation:{job.id}:{run.run_number}",
        )
    except ledger.LedgerError as exc:
        # Race lost between the pre-check and the reserve (another concurrent
        # spend won the balance). The transaction is aborted ATOMICALLY by the
        # ledger; do NOT continue on this transaction - surface loudly and let
        # the next sweep retry cleanly (nothing was committed).
        await session.rollback()
        log.warning(
            "automation_reserve_race_lost",
            job_id=job.id,
            budget=budget,
            error=str(exc),
        )
        raise
    task.reserved_xp = budget
    job.run_count += 1
    job.last_run_at = now
    job.next_run_at = next_run_after(job.schedule, now)
    await session.commit()

    # 6) Execute in its own session (the durable runner owns its commits).
    await execute_task(session_factory, task.id, settings)
    await session.refresh(task)
    await _finalize_run(session, job=job, run=run, task=task, settings=settings)
    await session.commit()
    return run


async def run_due_jobs(
    session: AsyncSession,
    settings: Settings,
    *,
    session_factory,
    execute_task: Executor | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Sweep every active, due job. Returns a compact per-job outcome list."""
    now = _naive(now) or datetime.now(UTC).replace(tzinfo=None)
    due = (
        (
            await session.execute(
                select(ScheduledJob)
                .where(
                    ScheduledJob.status == "active",
                    ScheduledJob.next_run_at.is_not(None),
                    ScheduledJob.next_run_at <= now,
                )
                .order_by(ScheduledJob.next_run_at)
            )
        )
        .scalars()
        .all()
    )
    results: list[dict[str, Any]] = []
    for job in due:
        try:
            run = await process_job(
                session,
                job,
                settings,
                session_factory=session_factory,
                execute_task=execute_task,
                now=now,
            )
        except Exception as exc:
            log.error("automation_job_failed", job_id=job.id, error=str(exc))
            results.append(
                {"job_id": job.id, "run_id": None, "status": "error", "error": str(exc)}
            )
            continue
        results.append(
            {
                "job_id": job.id,
                "run_id": run.id,
                "status": run.status,
                "xp_charged": run.xp_charged,
            }
        )
    return results
