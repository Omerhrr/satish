"""Agent runtime service (phase 6): durable DSH task execution.

Wires the PlanRunner into the application database so every deliverable of
dsh_integration is enforced by DETERMINISTIC backend code:

- Durable state: plan, steps, and events persist in task_steps/task_events
  and survive worker restarts (acceptance #3) — the runner holds no state
  that matters; a resumed run reconstructs from the DB.
- Budget-aware dispatch: the registry refuses a tool whose max_cost_xp
  exceeds the remaining budget; the ledger refuses settlement above the
  approved cap (acceptance #5).
- Approval gate: approval-required tools stop the run; the decision is an
  Approval row the USER creates through the API — the model cannot approve
  itself, and the digest binds the decision to the exact action
  (acceptance #2).
- Durable cancellation: the cancel endpoint flips task.status; the runner
  re-reads it between steps (acceptance #3/#5).
- Scope wall: scopes come from server-side policy, never from content;
  untrusted material is wrapped by the adapter's UNTRUSTED markers and
  cannot expand permissions (acceptance #4).
- No key material: the registry contains no wallet/signing/seed tools and
  the runtime injects no credentials into the agent context (acceptance #1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.research_tools import build_product_registry
from app.services.task_events import append_event, load_events
from dsh_adapter.client import make_chat_client
from dsh_adapter.evaluation import evaluate_run
from dsh_adapter.runner import PersistenceHooks, PlanRunner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import Approval, AuditEvent, Task, TaskStep
from xp_core.services import ledger
from xp_core.services.storage import LocalStorage


def _registry_for(session, task, settings, storage):
    """Registry seam (patch point for tests injecting custom registries)."""
    return build_product_registry(session=session, task=task, settings=settings, storage=storage)

log = get_logger(__name__)

# Server-side scope policy for user-initiated agent tasks (least privilege):
# tools NOT covered here are structurally unreachable, whatever the model
# plans. email:send / automation:write arrive with their product surfaces in
# later phases; their tools additionally carry requires_approval=True.
USER_TASK_SCOPES = {"research:read", "documents:write", "email:draft"}


class AgentRuntimeError(Exception):
    pass


class TaskNotRunnable(AgentRuntimeError):
    pass


# -- event stream helpers ------------------------------------------------------------
# append_event / load_events live in task_events.py (shared with the research
# tool handlers); re-exported here for the routers' import compatibility.


# -- persistence hooks --------------------------------------------------------------


class DbPersistenceHooks(PersistenceHooks):
    """Implements the runner's hooks on the application DB, committing as it
    goes so state survives a worker restart at any point."""

    def __init__(self, session: AsyncSession, task: Task) -> None:
        self.session = session
        self.task = task

    async def on_plan(self, plan: dict[str, Any]) -> None:
        # TaskStep rows = the durable plan; TaskEvent rows = the stream.
        for step in plan.get("plan", [])[:12]:
            step_index = int(step.get("step", 0))
            exists = (
                await self.session.execute(
                    select(TaskStep).where(
                        TaskStep.task_id == self.task.id,
                        TaskStep.step_index == step_index,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                self.session.add(
                    TaskStep(
                        task_id=self.task.id,
                        step_index=step_index,
                        tool_name=step.get("tool"),
                        status="pending",
                    )
                )
        await append_event(
            self.session,
            self.task.id,
            "plan.created",
            {
                "estimated_xp": plan.get("estimated_xp"),
                "deliverable": plan.get("deliverable"),
                "steps": [
                    {"step": s.get("step"), "tool": s.get("tool"), "why": s.get("why")}
                    for s in plan.get("plan", [])
                ],
            },
        )
        await self.session.commit()

    async def on_approval_required(self, action: dict[str, Any]) -> bool:
        """Determine approval from the DB — never from the model.

        If the user already approved THIS digest (resume case) return True.
        Otherwise create a pending Approval and stop the run.
        """
        digest = action.get("digest", "")
        tool = action.get("tool", "")
        approved = (
            await self.session.execute(
                select(Approval).where(
                    Approval.task_id == self.task.id,
                    Approval.action_digest == digest,
                    Approval.status == "approved",
                )
            )
        ).scalar_one_or_none()
        if approved is not None:
            await append_event(
                self.session,
                self.task.id,
                "approval.reused",
                {"tool": tool, "digest": digest, "approval_id": approved.id},
            )
            await self.session.commit()
            return True
        pending = Approval(
            user_id=self.task.user_id,
            task_id=self.task.id,
            action_type=f"tool.{tool}",
            action_digest=digest,
            status="pending",
        )
        self.session.add(pending)
        await self.session.flush()
        await append_event(
            self.session,
            self.task.id,
            "approval.requested",
            {"approval_id": pending.id, "tool": tool, "digest": digest},
        )
        await self.session.commit()
        return False

    async def on_step(
        self, step_index: int, tool_name: str | None, status: str, detail: dict[str, Any]
    ) -> None:
        row = (
            await self.session.execute(
                select(TaskStep).where(
                    TaskStep.task_id == self.task.id, TaskStep.step_index == step_index
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = TaskStep(task_id=self.task.id, step_index=step_index, tool_name=tool_name)
            self.session.add(row)
        row.tool_name = tool_name or row.tool_name
        row.status = status
        now = datetime.now(UTC)
        if status == "running":
            row.started_at = row.started_at or now
        elif status in {
            "completed",
            "denied",
            "rejected",
            "timeout",
            "cancelled",
            "invalid_arguments",
        }:
            row.completed_at = now

        # Tool-call audit record (deliverable #8): digest-level facts only —
        # never argument content, never tool output text.
        if tool_name and status in {
            "completed",
            "denied",
            "rejected",
            "timeout",
            "invalid_arguments",
        }:
            self.session.add(
                AuditEvent(
                    actor_type="agent",
                    event_type="tool.call",
                    resource_type="tool",
                    resource_id=tool_name,
                    request_id=str(self.task.id),
                    metadata_redacted={
                        "task_id": self.task.id,
                        "step_index": step_index,
                        "status": status,
                    },
                )
            )

        # Event payload keeps small structured facts; tool output is reduced
        # to shape (keys/status) so the stream stays replayable and clean.
        payload: dict[str, Any] = {"step": step_index, "tool": tool_name, "status": status}
        result = detail.get("result")
        if isinstance(result, dict):
            payload["result_status"] = result.get("status")
            payload["result_keys"] = sorted(str(k) for k in result)[:12]
        if "why" in detail:
            payload["why"] = str(detail["why"])[:300]
        await append_event(self.session, self.task.id, f"step.{status}", payload)
        await self.session.commit()

    async def on_complete(self, report: dict[str, Any]) -> None:
        # The durable plan is the set of TaskStep rows; the report's run steps
        # carry per-step outcomes.
        plan_rows = (
            await self.session.execute(
                select(TaskStep).where(TaskStep.task_id == self.task.id)
            )
        ).scalars().all()
        plan_view = [
            {"step": r.step_index, "tool": r.tool_name, "status": r.status} for r in plan_rows
        ]
        evaluation = evaluate_run(
            report=report, plan={"plan": plan_view}, steps=report.get("steps", [])
        )
        await append_event(
            self.session,
            self.task.id,
            "evaluation.completed",
            {
                "score": evaluation["score"],
                "completeness": evaluation["completeness"],
                "provenance": evaluation["provenance"],
                "consistency": evaluation["consistency"],
                "notes": evaluation["notes"],
            },
        )
        await append_event(
            self.session,
            self.task.id,
            "task.completed",
            {
                "deliverable": report.get("deliverable"),
                "spent_xp": report.get("spent_xp"),
                "sources": report.get("sources", []),
                "model_usage": report.get("model_usage"),
                "limitations": report.get("limitations", []),
            },
        )
        await self.session.commit()


# -- the run loop ---------------------------------------------------------------------


async def run_agent_task(
    session_factory, task_id: str, settings: Settings, *, resume: bool = False
) -> dict[str, Any]:
    """Execute one agent task end-to-end with durable state.

    Called by the worker job (arq) and inline by the dev bridge. Owns its
    sessions; the API router only enqueues.
    """
    async with session_factory() as session:
        task = (
            await session.execute(select(Task).where(Task.id == task_id))
        ).scalar_one_or_none()
        if task is None:
            raise TaskNotRunnable(f"task {task_id} not found")
        if task.status in {"completed", "failed", "cancelled"}:
            raise TaskNotRunnable(f"task {task_id} already {task.status}")

        # Resume support: skip steps the DB says completed.
        skip: set[int] = set()
        if resume:
            done = (
                await session.execute(
                    select(TaskStep.step_index).where(
                        TaskStep.task_id == task_id, TaskStep.status == "completed"
                    )
                )
            ).scalars().all()
            skip = {int(i) for i in done}

        task.status = "running"
        task.started_at = task.started_at or datetime.now(UTC)
        await append_event(
            session, task_id, "task.started", {"resume": resume, "skipped_steps": sorted(skip)}
        )
        await session.commit()

        hooks = DbPersistenceHooks(session, task)

        async def cancelled_in_db() -> bool:
            # Re-read committed state (a plain select always hits the DB).
            fresh_status = await session.scalar(
                select(Task.status).where(Task.id == task_id)
            )
            return fresh_status == "cancelled"

        runner = PlanRunner(
            make_chat_client(settings),
            _registry_for(
                session=session,
                task=task,
                settings=settings,
                storage=LocalStorage(settings.artifact_dir),
            ),
            persistence=hooks,
            max_steps=settings.agent_max_steps,
            should_cancel=cancelled_in_db,
        )

        outcome_status = "failed"
        spent = 0
        try:
            result = await runner.run(
                task.objective,
                scopes=set(USER_TASK_SCOPES),
                budget_xp=task.budget_xp,
                skip_steps=skip or None,
            )
            outcome_status = result.status
            spent = result.spent_xp

            if result.status == "completed":
                actual = min(spent, task.budget_xp)
                await ledger.settle_task(
                    session,
                    user_id=task.user_id,
                    task_id=task_id,
                    reserved_xp=task.reserved_xp,
                    actual_xp=actual,
                )
                task.reserved_xp = 0
                task.actual_xp = actual
                task.status = "completed"
                task.completed_at = datetime.now(UTC)
                task.deliverable = result.deliverable
                session.add(
                    AuditEvent(
                        actor_type="system",
                        event_type="task.settled",
                        resource_type="task",
                        resource_id=task_id,
                        metadata_redacted={"actual_xp": actual, "budget_xp": task.budget_xp},
                    )
                )
                await session.commit()
            elif result.status == "awaiting_approval":
                task.status = "awaiting_approval"
                await session.commit()
            elif result.status == "cancelled":
                # Durable cancel: release the untouched reservation.
                if task.reserved_xp > 0:
                    await ledger.release_reservation(
                        session,
                        user_id=task.user_id,
                        task_id=task_id,
                        amount=task.reserved_xp,
                    )
                    task.reserved_xp = 0
                    await session.commit()
            else:  # failed runner outcome
                task.status = "failed"
                task.error = "runner failed"
                task.completed_at = datetime.now(UTC)
                if task.reserved_xp > 0:
                    await ledger.release_reservation(
                        session,
                        user_id=task.user_id,
                        task_id=task_id,
                        amount=task.reserved_xp,
                    )
                    task.reserved_xp = 0
                await session.commit()
        except Exception as exc:
            await session.rollback()  # a poisoned tx must not carry forward
            task = (
                await session.execute(select(Task).where(Task.id == task_id))
            ).scalar_one()
            task.status = "failed"
            task.error = f"{type(exc).__name__}: {exc}"[:2000]
            task.completed_at = datetime.now(UTC)
            if task.reserved_xp > 0:
                await ledger.release_reservation(
                    session,
                    user_id=task.user_id,
                    task_id=task_id,
                    amount=task.reserved_xp,
                )
                task.reserved_xp = 0
            await append_event(
                session, task_id, "task.failed", {"error": task.error}
            )
            await session.commit()
            raise
        finally:
            fresh_status = await session.scalar(select(Task.status).where(Task.id == task_id))
            summary = {
                "task_id": task_id,
                "outcome": outcome_status,
                "status": fresh_status or "?",
                "spent_xp": spent,
            }
        log.info("agent_task_finished", **summary)
        return summary


__all__ = [
    "USER_TASK_SCOPES",
    "AgentRuntimeError",
    "DbPersistenceHooks",
    "TaskNotRunnable",
    "append_event",
    "load_events",
    "run_agent_task",
]
