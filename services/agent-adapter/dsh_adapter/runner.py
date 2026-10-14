"""PlanRunner — implements the plan's agent_execution_contract stages.

Stages: goal -> (clarify) -> plan+estimate -> approval gate -> typed tool
execution with least privilege -> evaluation -> artifact -> transparent
report. Durable state lives in the application database via the injected
persistence callbacks, never in transient model context (dsh_integration).
"""

from __future__ import annotations

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
    ) -> None:
        self.client = client
        self.registry = registry
        self.persistence = persistence or NullPersistence()
        self.max_steps = max_steps

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
        try:
            import json

            plan = json.loads(response.get("content", "{}"))
        except Exception:  # noqa: BLE001 - malformed model JSON -> safe empty plan
            plan = {"plan": [], "estimated_xp": 0, "deliverable": goal}
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
            status = (
                "invalid_arguments"
                if type(exc).__name__ == "InvalidArguments"
                else "denied"
            )
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
    ) -> RunResult:
        """Full loop with hard budget cap and step limit (bounded execution)."""
        plan = await self.draft_plan(goal, constraints)
        steps = plan.get("plan", [])[: self.max_steps]
        spent = 0
        run_steps: list[dict[str, Any]] = []
        for step in steps:
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
