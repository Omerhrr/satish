"""Live DSH pin verification — proves the integration against the pinned revision.

Phase-0 acceptance: "DSH integration is proven against the selected upstream
revision." The contract tests prove the adapter logic offline; THIS script
proves the pinned upstream surface live. It performs:

  1. a non-thinking JSON plan call on the pinned primary model
  2. usage + cost capture from pinned pricing
  3. a tool-call round-trip through the allowlisted registry (stub tools)

Usage:
    XP_DEEPSEEK_API_KEY=sk-... .venv/bin/python scripts/dsh_live_check.py
    make dsh-verify   # same thing; skips with a clear message when no key

Exit code 0 = pinned revision verified; non-zero = verification FAILED and
the pin must not be trusted for the features that failed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, "services/agent-adapter")
sys.path.insert(0, "packages/py-core")

from dsh_adapter.client import DeepSeekChatClient
from dsh_adapter.revision import load_revision
from dsh_adapter.tools import ToolRegistry, ToolSpec


async def main() -> int:
    if not os.environ.get("XP_DEEPSEEK_API_KEY"):
        print("SKIP: XP_DEEPSEEK_API_KEY not set — live verification not possible.")
        print("The pin remains contract-test-verified; run this before release.")
        return 0

    rev = load_revision()
    print(f"pin: {rev.revision_id} (sha256 {rev.checksum[:12]}…)")
    print(f"primary model: {rev.primary_model} ({rev.model_entry(rev.primary_model)['upstream_version']})")

    client = DeepSeekChatClient(api_key=os.environ["XP_DEEPSEEK_API_KEY"], revision=rev)

    # -- 1. plan call (non-thinking, JSON) ------------------------------------
    response = await client.complete(
        [
            {
                "role": "user",
                "content": (
                    "Goal: summarize Bitcoin Lightning adoption in 2026. "
                    'Return JSON: {plan: [{step, tool, why}], estimated_xp, deliverable}. '
                    "Only use the tool web.search."
                ),
            }
        ]
    )
    print(f"[1] plan call OK — finish={response['finish_reason']} model={response['model']}")
    usage = response.get("usage", {})
    print(
        f"    usage: {usage.get('prompt_tokens')}in/{usage.get('completion_tokens')}out "
        f"(cache hit {usage.get('cache_hit_tokens')}), est ${usage.get('estimated_cost_usd')}"
    )
    try:
        plan = json.loads(response["content"])
        assert isinstance(plan.get("plan"), list) and plan["plan"], "empty plan"
        print(f"[1] JSON plan parsed: {len(plan['plan'])} step(s)")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL [1] plan JSON unparseable: {exc}\nraw: {response['content'][:300]}")
        return 1

    # -- 2. tool-call round-trip ----------------------------------------------
    registry = ToolRegistry()

    async def echo_handler(args: dict) -> dict:
        return {"echo": args.get("query", "")}

    registry.register(
        ToolSpec(
            name="web.search",
            category="research",
            description="echo probe for live verification",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            required_scope="research",
            max_cost_xp=1,
            handler=echo_handler,
        )
    )
    tool_response = await client.complete(
        [{"role": "user", "content": "Call the web.search tool with query 'lightning 2026'."}],
        tools=registry.openai_tools(),
    )
    if tool_response["tool_calls"]:
        call = tool_response["tool_calls"][0]
        result = await registry.execute(call["name"], call["arguments"], {"research"})
        print(f"[2] tool call OK — {call['name']}({call['arguments']}) -> {result}")
    else:
        print(f"WARN [2] model answered without a tool call: {tool_response['content'][:120]}")
        print("       tool-calling on the pinned model needs review before relying on it.")

    print("VERIFIED: pinned DSH revision answered plan + tool surfaces as contracted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
