"""PlanRunner — implements the plan's agent_execution_contract stages.

Stages: goal -> (clarify) -> plan+estimate -> approval gate -> typed tool
execution with least privilege -> evaluation -> artifact -> transparent
report. Durable state lives in the application database via the injected
persistence callbacks, never in transient model context (dsh_integration).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from xp_core.logging import get_logger

from dsh_adapter.client import SYSTEM_POLICY, ChatClient
from dsh_adapter.tools import ToolRegistry, ToolRegistryError, ToolSpec

log = get_logger(__name__)


class PersistenceHooks(Protocol):
    """Adapter-to-application callbacks; the API implements these on its DB."""

    async def on_plan(self, plan: dict[str, Any]) -> None: ...
    async def on_approval_required(self, action: dict[str, Any]) -> bool: ...
    async def on_step(
        self, step_index: int, tool_name: str | None, status: str, detail: dict[str, Any]
    ) -> None: ...
    async def on_complete(self, report: dict[str, Any]) -> None: ...


class NullPersistence:
    """No-op hooks for tests/scaffold runs."""

    async def on_plan(self, plan: dict[str, Any]) -> None: ...
    async def on_approval_required(self, action: dict[str, Any]) -> bool:
        return False

    async def on_step(
        self, step_index: int, tool_name: str | None, status: str, detail: dict[str, Any]
    ) -> None: ...
    async def on_complete(self, report: dict[str, Any]) -> None: ...


@dataclass
class RunResult:
    status: str  # completed | awaiting_approval | failed
    deliverable: str | None = None
    estimated_xp: int = 0
    spent_xp: int = 0
    steps: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


class PlanRunner:
    def __init__(
        self,
        client: ChatClient,
        registry: ToolRegistry,
        persistence: PersistenceHooks | None = None,
        max_steps: int = 12,
        should_cancel: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.persistence = persistence or NullPersistence()
        self.max_steps = max_steps
        # Cancellation (1) cooperative in-process flag — cancel() from any
        # task; (2) durable check — should_cancel() is awaited between steps
        # so a cancel recorded in the DB stops a worker run mid-flight
        # (phase-6 acceptance: task states persist across worker restarts).
        self._cancel_event = asyncio.Event()
        self._should_cancel = should_cancel
        # Model usage ledger for this runner instance: one entry per model
        # call (dsh_integration requirement #8 — track cost where measurable).
        self.model_usage: list[dict[str, Any]] = []

    async def _cancelled_durably(self) -> bool:
        if self._cancel_event.is_set():
            return True
        if self._should_cancel is not None:
            return bool(await self._should_cancel())
        return False

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _record_usage(self, response: dict[str, Any]) -> None:
        usage = response.get("usage")
        if usage:
            self.model_usage.append(
                {
                    "model": response.get("model"),
                    "revision_id": response.get("revision_id"),
                    **usage,
                }
            )

    def _usage_summary(self) -> dict[str, Any]:
        total_cost = 0.0
        cost_known = True
        prompt = completion = cache_hit = 0
        for u in self.model_usage:
            prompt += u.get("prompt_tokens", 0) or 0
            completion += u.get("completion_tokens", 0) or 0
            cache_hit += u.get("cache_hit_tokens", 0) or 0
            cost = u.get("estimated_cost_usd")
            if cost is None:
                cost_known = False
            else:
                total_cost += cost
        summary: dict[str, Any] = {
            "model_calls": len(self.model_usage),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_hit_tokens": cache_hit,
            "estimated_cost_usd": round(total_cost, 6) if cost_known else None,
        }
        if not cost_known:
            summary["cost_note"] = "some model calls have no pinned pricing; estimate omitted"
        return summary

    async def draft_plan(self, goal: str, constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stage 1-3: goal + constraints -> plan, deliverable, XP estimate."""
        messages = [
            {"role": "system", "content": SYSTEM_POLICY},
            {
                "role": "user",
                "content": (
                    f"Goal: {goal}\n"
                    f"Constraints: {constraints or {}}\n"
                    "Return JSON: {plan: [{step, tool, why}], estimated_xp, deliverable}. "
                    "Only use registered tools."
                ),
            },
        ]
        response = await self.client.complete(messages, tools=self.registry.openai_tools())
        self._record_usage(response)
        try:
            import json

            plan = json.loads(response.get("content", "{}"))
        except Exception:
            plan = {"plan": [], "estimated_xp": 0, "deliverable": goal}
        plan["model_usage"] = self._usage_summary()
        await self.persistence.on_plan(plan)
        return plan

    async def execute_step(
        self,
        step: dict[str, Any],
        scopes: set[str],
        budget_remaining_xp: int,
        untrusted_context: str | None = None,
    ) -> dict[str, Any]:
        """Execute one planned step through the allowlisted registry."""
        tool_name = step.get("tool")
        await self.persistence.on_step(int(step.get("step", 0)), tool_name, "running", {})
        if not tool_name:
            await self.persistence.on_step(int(step.get("step", 0)), None, "skipped", {"why": "no tool"})
            return {"status": "skipped"}
        try:
            spec: ToolSpec = self.registry.get(tool_name)
        except ToolRegistryError as exc:
            await self.persistence.on_step(int(step.get("step", 0)), tool_name, "rejected", {"why": str(exc)})
            return {"status": "rejected", "reason": str(exc)}
        # Scope wall FIRST: never request user approval for something the
        # granted scopes would deny anyway, and never let an approval expand
        # scopes (the scope set is server-side policy, not negotiable).
        if not self.registry.allowed(tool_name, scopes):
            await self.persistence.on_step(
                int(step.get("step", 0)), tool_name, "denied", {"why": f"scope {spec.required_scope!r} not granted"}
            )
            return {"status": "denied", "reason": "scope not granted"}
        if spec.max_cost_xp > budget_remaining_xp:
            await self.persistence.on_step(int(step.get("step", 0)), tool_name, "rejected", {"why": "budget"})
            return {"status": "rejected", "reason": "insufficient budget"}
        if spec.requires_approval:
            approved = await self.persistence.on_approval_required(
                {"tool": tool_name, "digest": spec.action_digest(step.get("arguments", {}))}
            )
            if not approved:
                await self.persistence.on_step(int(step.get("step", 0)), tool_name, "awaiting_approval", {})
                return {"status": "awaiting_approval"}
        arguments = dict(step.get("arguments", {}))
        try:
            result = await self.registry.execute(tool_name, arguments, scopes)
        except ToolRegistryError as exc:
            from dsh_adapter.tools import InvalidArguments, ToolTimeout

            if isinstance(exc, InvalidArguments):
                status = "invalid_arguments"
            elif isinstance(exc, ToolTimeout):
                status = "timeout"
            else:
                status = "denied"
            await self.persistence.on_step(
                int(step.get("step", 0)), tool_name, status, {"why": str(exc)}
            )
            return {"status": status, "reason": str(exc)}
        await self.persistence.on_step(
            int(step.get("step", 0)), tool_name, "completed", {"result": result}
        )
        return {"status": "completed", "result": result}

    async def run(
        self,
        goal: str,
        *,
        scopes: set[str],
        budget_xp: int,
        constraints: dict[str, Any] | None = None,
        untrusted_context: str | None = None,
        skip_steps: set[int] | None = None,
    ) -> RunResult:
        """Full loop with hard budget cap and step limit (bounded execution).

        skip_steps: indexes already persisted as completed on a resume run —
        durable-state resume after approval or worker restart.
        """
        plan = await self.draft_plan(goal, constraints)
        steps = [
            s
            for s in plan.get("plan", [])[: self.max_steps]
            if skip_steps is None or int(s.get("step", 0)) not in skip_steps
        ]
        spent = 0
        run_steps: list[dict[str, Any]] = []
        for step in steps:
            if self.cancelled or await self._cancelled_durably():
                await self.persistence.on_step(
                    int(step.get("step", 0)), step.get("tool"), "cancelled", {}
                )
                return RunResult(
                    status="cancelled",
                    deliverable=plan.get("deliverable"),
                    estimated_xp=int(plan.get("estimated_xp", 0)),
                    spent_xp=spent,
                    steps=run_steps,
                    report={"goal": goal, "model_usage": self._usage_summary()},
                )
            tool_name = step.get("tool")
            cost = 0
            if tool_name and self.registry.allowed(tool_name, scopes):
                cost = self.registry.get(tool_name).max_cost_xp
            outcome = await self.execute_step(step, scopes, budget_xp - spent, untrusted_context)
            run_steps.append({"step": step.get("step"), "tool": step.get("tool"), **outcome})
            if outcome["status"] == "completed":
                spent += cost
            if outcome["status"] == "awaiting_approval":
                return RunResult(
                    status="awaiting_approval",
                    deliverable=plan.get("deliverable"),
                    estimated_xp=int(plan.get("estimated_xp", 0)),
                    spent_xp=spent,
                    steps=run_steps,
                )
        report = {
            "goal": goal,
            "deliverable": plan.get("deliverable"),
            "estimated_xp": int(plan.get("estimated_xp", 0)),
            "spent_xp": spent,
            "steps": run_steps,
            "model_usage": self._usage_summary(),
            "limitations": ["scaffold: research tools are stubs until phase 4"],
            "sources": [],
        }
        await self.persistence.on_complete(report)
        return RunResult(
            status="completed",
            deliverable=plan.get("deliverable"),
            estimated_xp=int(plan.get("estimated_xp", 0)),
            spent_xp=spent,
            steps=run_steps,
            report=report,
        )
