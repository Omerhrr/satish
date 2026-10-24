"""How Satish AI copes with a real model's replies (not the built-in stub)."""

from __future__ import annotations

import json

from dsh_adapter.runner import PlanRunner
from dsh_adapter.tools import default_registry


class Scripted:
    """Replies like a real model: json_mode for plans, prose for answers."""

    def __init__(self, plan_text: str, answer_text: str = "Here is what I found."):
        self.plan_text, self.answer_text = plan_text, answer_text
        self.calls: list[dict] = []

    async def complete(self, messages, tools=None, json_mode=False):
        self.calls.append({"json_mode": json_mode, "tools": tools, "prompt": messages[-1]["content"]})
        return {
            "content": self.plan_text if json_mode else self.answer_text,
            "tool_calls": [], "finish_reason": "stop", "model": "deepseek-flash", "revision_id": "t",
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "cache_hit_tokens": 0, "estimated_cost_usd": 0.0},
        }


async def test_hello_is_answered_directly_in_one_call():
    m = Scripted(json.dumps({"answer": "Hi! How can I help?", "plan": [], "estimated_xp": 0, "deliverable": "a reply"}))
    result = await PlanRunner(m, default_registry()).run("hello", scopes={"research"}, budget_xp=100)
    assert result.status == "completed"
    assert result.report["answer"] == "Hi! How can I help?"
    assert len(m.calls) == 1 and m.calls[0]["json_mode"] is True


async def test_tools_are_described_in_text_never_sent_as_functions():
    m = Scripted(json.dumps({"answer": "ok", "plan": []}))
    await PlanRunner(m, default_registry()).draft_plan("hello")
    assert m.calls[0]["tools"] is None  # "web.search" is not a valid function name for the API
    assert "web.search(" in m.calls[0]["prompt"]


async def test_fenced_json_and_loose_tool_names_still_work():
    fenced = "```json\n" + json.dumps({
        "answer": None,
        "plan": [{"step": 1, "tool": "web_search", "why": "prices", "arguments": {"query": "rice price kaduna"}}],
        "estimated_xp": 5, "deliverable": "price summary",
    }) + "\n```"
    m = Scripted(fenced, answer_text="A 50kg bag costs about N80,000 (sample).")
    result = await PlanRunner(m, default_registry()).run("rice prices in Kaduna", scopes={"research"}, budget_xp=100)
    assert result.steps and result.steps[0]["tool"] == "web.search"
    assert result.report["answer"].startswith("A 50kg bag")
    assert [c["json_mode"] for c in m.calls] == [True, False]  # plan, then the written answer
    assert "UNTRUSTED" in m.calls[1]["prompt"]


async def test_model_ignoring_the_format_becomes_the_answer_not_a_failure():
    m = Scripted("Hello! I'm Satish AI. Ask me anything.")
    result = await PlanRunner(m, default_registry()).run("hello", scopes={"research"}, budget_xp=100)
    assert result.status == "completed"
    assert result.report["answer"].startswith("Hello! I'm Satish AI")


async def test_unknown_tools_are_dropped():
    m = Scripted(json.dumps({"plan": [{"step": 1, "tool": "hack.the.planet"}], "answer": "fallback"}))
    plan = await PlanRunner(m, default_registry()).draft_plan("x")
    assert plan["plan"] == [] and plan["answer"] == "fallback"
