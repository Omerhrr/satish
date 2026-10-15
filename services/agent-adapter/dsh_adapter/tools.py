"""Typed tool registry with allowlist semantics.

Every tool declares: JSON-schema inputs, required scope, XP cost budget,
timeout, and whether user approval is required before execution
(dsh_integration requirements: schemas, permissions, budgets, timeouts).
The registry is the ONLY way tools reach the model runtime, and unknown or
out-of-scope tools are rejected here — defense in depth against model-driven
privilege escalation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class ToolRegistryError(Exception):
    pass


class UnknownTool(ToolRegistryError):
    pass


class ScopeDenied(ToolRegistryError):
    pass


class InvalidArguments(ToolRegistryError):
    pass


class ToolTimeout(ToolRegistryError):
    """Raised when a tool exceeds its spec timeout — deterministic backend
    enforcement (phase-6 acceptance: budget limits and tool timeouts are
    enforced by deterministic backend code, never by the model's goodwill)."""

    pass


@dataclass(slots=True)
class ToolSpec:
    name: str
    category: str  # research | commerce_intelligence | documents | communication | automation
    description: str
    input_schema: dict[str, Any]
    required_scope: str
    max_cost_xp: int = 0
    timeout_seconds: int = 30
    requires_approval: bool = False
    handler: ToolHandler | None = None

    def openai_definition(self) -> dict[str, Any]:
        """OpenAI-compatible tool definition (DeepSeek uses the same format)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def action_digest(self, arguments: dict[str, Any]) -> str:
        """Stable digest of a concrete action for approval records (approvals.action_digest)."""
        canonical = json.dumps(
            {"tool": self.name, "args": arguments}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class ToolRegistry:
    allowlisted_categories: set[str] = field(
        default_factory=lambda: {
            "research",
            "commerce_intelligence",
            "documents",
            "communication",
            "automation",
        }
    )
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if spec.category not in self.allowlisted_categories:
            raise ToolRegistryError(f"category {spec.category!r} is not allowlisted")
        if spec.name in self._tools:
            raise ToolRegistryError(f"tool {spec.name!r} already registered")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownTool(f"tool {name!r} is not registered") from exc

    def allowed(self, name: str, scopes: set[str]) -> bool:
        try:
            spec = self.get(name)
        except UnknownTool:
            return False
        return spec.required_scope in scopes

    async def execute(
        self, name: str, arguments: dict[str, Any], scopes: set[str]
    ) -> dict[str, Any]:
        """Execute an allowlisted tool within the granted scopes.

        Enforcement happens HERE, in deterministic backend code: scope check,
        schema check, then a hard asyncio timeout from the tool spec.
        """
        spec = self.get(name)
        if not self.allowed(name, scopes):
            raise ScopeDenied(
                f"scope {spec.required_scope!r} not granted for tool {name!r}"
            )
        # Minimal JSON-schema enforcement: required fields present.
        required = spec.input_schema.get("required", []) or []
        missing = [field for field in required if field not in arguments]
        if missing:
            raise InvalidArguments(f"{name}: missing required arguments {missing}")
        if spec.handler is None:
            return {"status": "not_implemented", "tool": name}
        try:
            return await asyncio.wait_for(spec.handler(**arguments), timeout=spec.timeout_seconds)
        except TimeoutError as exc:
            raise ToolTimeout(
                f"{name} exceeded its {spec.timeout_seconds}s timeout"
            ) from exc

    def list_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def openai_tools(self) -> list[dict[str, Any]]:
        return [spec.openai_definition() for spec in self._tools.values()]


def default_registry() -> ToolRegistry:
    """Scaffold tool set mapped from plan tool_categories."""
    registry = ToolRegistry()

    async def web_search(query: str, limit: int = 5) -> dict[str, Any]:
        # Real search provider integration is a phase-4+ deliverable.
        return {"status": "stub", "query": query, "results": [], "limit": limit}

    async def fetch_page(url: str) -> dict[str, Any]:
        # Treats fetched content as UNTRUSTED downstream (execution contract #6).
        return {"status": "stub", "url": url, "content_ref": None}

    async def generate_pdf(title: str, sections: list[str]) -> dict[str, Any]:
        return {"status": "stub", "artifact_hint": {"title": title, "sections": sections}}

    async def draft_email(to: str, subject: str, body: str) -> dict[str, Any]:
        return {"status": "drafted", "to": to, "subject": subject, "body": body}

    async def send_email(to: str, subject: str, body: str) -> dict[str, Any]:
        return {"status": "stub_requires_approval", "to": to, "subject": subject}

    async def schedule_job(schedule: str, objective: str) -> dict[str, Any]:
        return {"status": "stub", "schedule": schedule, "objective": objective}

    registry.register(
        ToolSpec(
            name="web.search",
            category="research",
            description="Search permitted public web sources and return ranked results.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            required_scope="research:read",
            max_cost_xp=5,
            timeout_seconds=20,
            handler=web_search,
        )
    )
    registry.register(
        ToolSpec(
            name="web.fetch_page",
            category="research",
            description="Fetch a permitted public page for structured extraction.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "format": "uri"}},
                "required": ["url"],
            },
            required_scope="research:read",
            max_cost_xp=2,
            timeout_seconds=25,
            handler=fetch_page,
        )
    )
    registry.register(
        ToolSpec(
            name="docs.generate_pdf",
            category="documents",
            description="Generate a PDF report artifact from structured sections.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "sections": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "sections"],
            },
            required_scope="documents:write",
            max_cost_xp=10,
            timeout_seconds=120,
            handler=generate_pdf,
        )
    )
    registry.register(
        ToolSpec(
            name="email.draft",
            category="communication",
            description="Draft an email for user review. Never sends.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
            required_scope="email:draft",
            max_cost_xp=1,
            timeout_seconds=15,
            handler=draft_email,
        )
    )
    registry.register(
        ToolSpec(
            name="email.send",
            category="communication",
            description="Send an email. REQUIRES explicit user approval first.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
            required_scope="email:send",
            max_cost_xp=2,
            timeout_seconds=30,
            requires_approval=True,
            handler=send_email,
        )
    )
    registry.register(
        ToolSpec(
            name="automation.schedule",
            category="automation",
            description="Create a scheduled research/monitoring job within granted scopes.",
            input_schema={
                "type": "object",
                "properties": {
                    "schedule": {"type": "string"},
                    "objective": {"type": "string"},
                },
                "required": ["schedule", "objective"],
            },
            required_scope="automation:write",
            max_cost_xp=3,
            timeout_seconds=15,
            requires_approval=True,
            handler=schedule_job,
        )
    )
    return registry
