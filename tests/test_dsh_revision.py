"""Phase-0 DSH revision-pinning spike tests.

Covers the dsh_integration requirements the spike targets:
- pinned, structurally valid upstream revision with a drift gate (checksum)
- discontinued legacy model names can never reach the wire
- client derives model/base_url from the pin
- bounded retries, concurrency limit, output cap, usage + cost capture
- runner records model usage and honours cancellation
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from dsh_adapter.client import DeepSeekChatClient, StubChatClient, make_chat_client
from dsh_adapter.revision import (
    LegacyModelError,
    RevisionError,
    canonical_checksum,
    load_revision,
)
from dsh_adapter.runner import PlanRunner
from dsh_adapter.tools import default_registry

# ---------------------------------------------------------------------------
# Drift gate: editing dsh_revision.json requires consciously updating this
# constant — the pin must never move silently.
# ---------------------------------------------------------------------------
EXPECTED_MANIFEST_SHA256 = "6be7b9cc10776ef456f34f6fefbee42016e8272642043d8cc05cc17141bcea4c"


@pytest.fixture()
def revision():
    return load_revision()


# -- pin integrity -----------------------------------------------------------


def test_manifest_checksum_matches_drift_gate(revision):
    assert revision.checksum == EXPECTED_MANIFEST_SHA256
    assert canonical_checksum() == revision.checksum


def test_pin_structure_and_revision_id(revision):
    assert revision.revision_id.startswith("dsh-pin-")
    assert revision.primary_model == "deepseek-flash"
    assert revision.heavy_model == "deepseek-v4-pro"
    primary = revision.model_entry(revision.primary_model)
    assert primary["upstream_version"].startswith("DeepSeek-V4")
    assert primary["capabilities"]["tool_calls"] is True
    assert primary["pricing_usd_per_1m_tokens"]["output"]["off_peak"] == 0.6


def test_legacy_discontinued_alias_rejected(revision):
    with pytest.raises(LegacyModelError):
        revision.validate_model("deepseek-chat")
    with pytest.raises(LegacyModelError):
        revision.validate_model("deepseek-reasoner")


def test_retired_but_served_alias_allowed_with_warning(revision):
    assert revision.validate_model("deepseek-v4-flash") == "deepseek-v4-flash"


def test_unknown_model_rejected(revision):
    with pytest.raises(RevisionError):
        revision.validate_model("gpt-4o")


# -- client wiring -------------------------------------------------------------


def test_client_defaults_to_pinned_primary(revision):
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    assert client.model == revision.primary_model
    assert client.base_url == revision.base_url
    limits = revision.limits
    assert client.max_retries == limits["max_retries"]
    assert client.max_concurrent == limits["max_concurrent_requests"]
    assert client.max_output_chars == limits["max_output_chars"]


def test_client_configured_legacy_alias_fails_loudly(revision):
    with pytest.raises(LegacyModelError):
        DeepSeekChatClient(api_key="sk-test", model="deepseek-chat", revision=revision)


def test_make_chat_client_real_mode_uses_pin():
    from xp_core.config import Settings

    settings = Settings(deepseek_api_key="sk-test", deepseek_model=None, _env_file=None)
    client = make_chat_client(settings)
    assert isinstance(client, DeepSeekChatClient)
    assert client.model == "deepseek-flash"


def test_make_chat_client_stub_mode_without_key():
    from xp_core.config import Settings

    settings = Settings(deepseek_api_key=None, _env_file=None)
    client = make_chat_client(settings)
    assert isinstance(client, StubChatClient)


class FakeCompletions:
    """Scripted transport: pops canned outcomes (Exception instances raised)."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def create(self, **kwargs):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        finally:
            self.in_flight -= 1


def make_response(content="ok", prompt_tokens=100, completion_tokens=50, cache_hit=0):
    from types import SimpleNamespace

    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_cache_hit_tokens=cache_hit,
    )
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=None, reasoning_content=None),
        finish_reason="stop",
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def attach(client: DeepSeekChatClient, fake: FakeCompletions) -> None:
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))




@pytest.fixture()
def no_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr("dsh_adapter.client._sleep", fake_sleep)
    return sleeps


# -- resilience: retries -------------------------------------------------------


async def test_retry_on_503_then_success(revision, no_sleep):
    fake = FakeCompletions(
        [_make_status_error(503), _make_status_error(503), make_response("fine")]
    )
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, fake)
    out = await client.complete([{"role": "user", "content": "hi"}])
    assert out["content"] == "fine"
    assert fake.calls == 3
    assert len(no_sleep) == 2  # backed off between attempts


async def test_no_retry_on_permanent_400(revision, no_sleep):
    fake = FakeCompletions([_make_status_error(400), make_response("never")])
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, fake)
    with pytest.raises(Exception):  # noqa: B017
        await client.complete([{"role": "user", "content": "hi"}])
    assert fake.calls == 1
    assert no_sleep == []


async def test_retries_exhausted_raises_last(revision, no_sleep):
    fake = FakeCompletions([_make_status_error(429) for _ in range(5)])
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, fake)
    with pytest.raises(Exception):  # noqa: B017
        await client.complete([{"role": "user", "content": "hi"}])
    assert fake.calls == client.max_retries + 1


def _make_status_error(status: int) -> Exception:
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.deepseek.com/test")
    response = httpx.Response(status_code=status, request=request)
    return openai.APIStatusError(f"upstream {status}", response=response, body=None)


# -- concurrency + output cap + usage ------------------------------------------


async def test_concurrency_semaphore_bounds_in_flight(revision):
    fake = FakeCompletions([make_response(f"m{i}") for i in range(6)])
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, fake)
    await asyncio.gather(
        *[client.complete([{"role": "user", "content": "x"}]) for _ in range(6)]
    )
    assert fake.max_in_flight <= client.max_concurrent


async def test_output_cap_truncates(revision):
    long_text = "x" * (revision.limits["max_output_chars"] + 500)
    fake = FakeCompletions([make_response(long_text)])
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, fake)
    out = await client.complete([{"role": "user", "content": "hi"}])
    assert len(out["content"]) < len(long_text)
    assert out["content"].endswith("output-size limit]")


async def test_usage_and_cost_captured(revision):
    fake = FakeCompletions([make_response(prompt_tokens=1_000_000, completion_tokens=10_000)])
    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, fake)
    out = await client.complete([{"role": "user", "content": "hi"}])
    # 1M prompt + 10k completion @ off-peak flash pricing: 0.15 + 0.006 = 0.156
    assert out["usage"]["estimated_cost_usd"] == pytest.approx(0.156, abs=1e-4)
    assert out["revision_id"] == revision.revision_id


def test_thinking_toggle_sent_non_thinking_default(revision):
    captured: dict = {}

    class Probe(FakeCompletions):
        async def create(self, **kwargs):
            captured.update(kwargs)
            return make_response("ok")

    client = DeepSeekChatClient(api_key="sk-test", revision=revision)
    attach(client, Probe([]))
    asyncio.run(client.complete([{"role": "user", "content": "hi"}]))
    assert captured["extra_body"]["thinking"]["type"] == "disabled"
    assert "temperature" not in captured  # V4.x: sampling params inert — not sent


def test_cost_estimator_math(revision):
    # 2M cache-hit + 1M cache-miss + 0.5M output, flash off-peak:
    # 2*0.003 + 1*0.15 + 0.5*0.6 = 0.456
    est = revision.estimate_cost_usd(
        revision.primary_model, 3_000_000, 500_000, cache_hit_tokens=2_000_000
    )
    assert est == pytest.approx(0.456, abs=1e-6)
    assert revision.estimate_cost_usd("unknown-model", 10, 10) is None


# -- runner integration ------------------------------------------------------------


async def test_runner_records_model_usage_in_report(revision):
    runner = PlanRunner(StubChatClient(), default_registry())
    result = await runner.run(
        "write a report", scopes={"research", "documents"}, budget_xp=100
    )
    assert result.status == "completed"
    summary = result.report["model_usage"]
    assert summary["model_calls"] == 1
    assert summary["estimated_cost_usd"] == 0.0
    assert summary["prompt_tokens"] == 0


async def test_runner_cancellation_between_steps(revision):
    class CancelAfterPlan:
        def __init__(self):
            self.runner = None

        async def complete(self, messages, tools=None):
            self.runner.cancel()
            return await StubChatClient().complete(messages, tools)

    probe = CancelAfterPlan()
    runner = PlanRunner(probe, default_registry())
    probe.runner = runner
    result = await runner.run("x", scopes={"research"}, budget_xp=100)
    assert result.status == "cancelled"
    assert result.report["model_usage"]["model_calls"] == 1


async def test_plan_json_embedding_of_usage(revision):
    runner = PlanRunner(StubChatClient(), default_registry())
    plan = await runner.draft_plan("goal")
    assert plan["model_usage"]["model_calls"] == 1


# -- manifest JSON sanity (bytes on disk) -----------------------------------------


def test_manifest_json_parses_and_has_sources():
    data = json.loads(
        (canonical_manifest_path()).read_text(encoding="utf-8")
    )
    assert len(data["sources"]) >= 3
    assert data["models"]["primary"]["name"] == "deepseek-flash"


def canonical_manifest_path():
    from dsh_adapter.revision import MANIFEST_PATH

    return MANIFEST_PATH
