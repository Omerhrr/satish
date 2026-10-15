"""Phase-9 tests: email + automation workflows.

Acceptance coverage (plan phases[9]):
- "External actions require valid authorization and approved scope" ->
  test_send_without_connection_refused / test_revoke_blocks_send /
  test_scope_set_grants_email_and_automation
- "Approval is bound to the specific action content and expires" ->
  test_expired_pending_approval_cannot_be_approved /
  test_stale_approved_approval_re_requests / test_draft_digest_binds_content
- "Users can revoke connected services" -> test_link_list_revoke_flow +
  test_revocation_deletes_the_credential_row
- "Recurring jobs enforce per-run XP limits and total limits where
  configured" -> test_per_run_budget_is_the_task_cap /
  test_total_budget_exhausted_auto_pauses / test_insufficient_balance_skips
- "Failed jobs do not silently repeat consequential actions" ->
  test_consecutive_failures_auto_pause / test_blocked_run_waits_for_approval /
  test_denied_approval_fails_run_without_repeat
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import (
    Approval,
    AutomationRun,
    ScheduledJob,
    ServiceCredential,
    Task,
)
from xp_core.services import automation as automation_core
from xp_core.services import ledger
from xp_core.services import vault as vault_mod

# -- fixtures ---------------------------------------------------------------------


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
def factory(session):
    from xp_core.db import get_session_factory

    return get_session_factory()


@pytest.fixture()
async def smtp_connection(client):
    """A linked canned-capable smtp connection for the dev user."""
    resp = await client.post(
        "/api/v1/connections",
        json={
            "provider": "smtp",
            "credential": {
                "host": "smtp.example.test",
                "port": 587,
                "username": "agent@example.test",
                "password": "hunter2-secret",
                "starttls": True,
            },
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def email_plan() -> dict:
    return {
        "plan": [
            {
                "step": 1,
                "tool": "email.draft",
                "why": "prepare",
                "arguments": {
                    "to": "client@example.test",
                    "subject": "Weekly research digest",
                    "body": "Findings from this week's research, as approved.",
                },
            },
            {
                "step": 2,
                "tool": "email.send",
                "why": "deliver",
                "arguments": {
                    "to": "client@example.test",
                    "subject": "Weekly research digest",
                    "body": "Findings from this week's research, as approved.",
                },
            },
        ],
        "estimated_xp": 3,
        "deliverable": "digest sent",
    }


class ScriptedClient:
    """Deterministic stand-in for the DeepSeek client (same as phase-6 tests)."""

    def __init__(self, plan: dict) -> None:
        self.plan = plan

    async def complete(self, messages, tools=None):
        return {
            "content": json.dumps(self.plan),
            "tool_calls": [],
            "finish_reason": "stop",
            "model": "scripted",
            "revision_id": "test",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "cache_hit_tokens": 0,
                "estimated_cost_usd": 0.000001,
            },
        }


async def seed_xp(session, dev_user, amount: int) -> None:
    await ledger.credit_purchase(
        session, user_id=dev_user.id, amount=amount, payment_intent_id=f"seed-{amount}"
    )
    await session.commit()


async def make_second_user(session) -> tuple:
    from xp_core.models.entities import User
    from xp_core.services.security import create_session

    user = User(display_name="Other User")
    session.add(user)
    await session.flush()
    token, _row = await create_session(session, user.id)
    await session.commit()
    return user, token


# -- vault: scoped credential storage ----------------------------------------------


@pytest.mark.asyncio
async def test_credential_roundtrip_and_wrong_key(session, settings):
    payload = {"host": "h", "port": 587, "username": "u", "password": "p"}
    token = vault_mod.encrypt_payload(payload, settings)
    assert vault_mod.decrypt_payload(token, settings) == payload

    class OtherSettings:
        dev_mode = settings.dev_mode
        connections_credential_key = "a-different-master-key"

    with pytest.raises(vault_mod.ConnectionError):
        vault_mod.decrypt_payload(token, OtherSettings())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_non_dev_without_master_key_refused(session, settings):
    class ProdSettings:
        dev_mode = False
        connections_credential_key = None

    with pytest.raises(vault_mod.ConnectionError):
        vault_mod.encrypt_payload({"host": "h"}, ProdSettings())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_link_list_revoke_flow(client, session, smtp_connection):
    conn = smtp_connection
    assert conn["provider"] == "smtp"
    assert set(conn["scopes"]) == {"email:draft", "email:send"}
    assert conn["credential_reference"].startswith("vault:")
    assert conn["disclosure"], "dev fallback key is disclosed"

    listed = (await client.get("/api/v1/connections")).json()
    assert [c["id"] for c in listed] == [conn["id"]]
    # NO secret ever surfaces in the API response:
    assert "hunter2-secret" not in json.dumps(listed)
    assert "password" not in json.dumps(listed)

    revoked = await client.delete(f"/api/v1/connections/{conn['id']}")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert "hunter2-secret" not in revoked.text

    again = await client.delete(f"/api/v1/connections/{conn['id']}")
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_revocation_deletes_the_credential_row(
    client, session, dev_user, smtp_connection
):
    conn = smtp_connection
    row = (
        await session.execute(
            select(ServiceCredential).where(
                ServiceCredential.connection_id == conn["id"]
            )
        )
    ).scalar_one()
    assert row is not None
    await client.delete(f"/api/v1/connections/{conn['id']}")
    await session.commit()
    remaining = (
        await session.execute(
            select(ServiceCredential).where(
                ServiceCredential.connection_id == conn["id"]
            )
        )
    ).scalar_one_or_none()
    assert remaining is None, "revocation hard-deletes the stored credential"


@pytest.mark.asyncio
async def test_unknown_provider_and_missing_fields_refused(client, session):
    pigeon = await client.post(
        "/api/v1/connections",
        json={"provider": "carrier_pigeon", "credential": {"name": "Errol"}},
    )
    assert pigeon.status_code == 422

    incomplete = await client.post(
        "/api/v1/connections",
        json={"provider": "smtp", "credential": {"host": "h", "port": 587}},
    )
    assert incomplete.status_code == 422
    assert "password" in incomplete.json()["detail"]


@pytest.mark.asyncio
async def test_scope_set_grants_email_and_automation():
    from app.services.agent_service import USER_TASK_SCOPES

    assert {"email:draft", "email:send", "automation:write"} <= USER_TASK_SCOPES


# -- email draft -> preview -> approval -> send --------------------------------------


@pytest.mark.asyncio
async def test_draft_digest_binds_content(session, dev_user):
    from app.services.research_tools import content_digest

    d1 = content_digest("a@b.c", "s", "b")
    d2 = content_digest("a@b.c", "s", "b")
    d3 = content_digest("a@b.c", "s", "b-changed")
    assert d1 == d2 and d1 != d3 and len(d1) == 64


@pytest.mark.asyncio
async def test_send_without_connection_refused(
    client, session, dev_user, factory, monkeypatch
):
    """No linked service: the send refuses, and the draft stays usable."""
    from app.services import agent_service

    await seed_xp(session, dev_user, 100)
    monkeypatch.setattr(
        agent_service, "make_chat_client", lambda settings: ScriptedClient(email_plan())
    )
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Send digest", "budget_xp": 20}
        )
    ).json()
    await client.post(f"/api/v1/tasks/{task['id']}/run")
    approvals = (await client.get(f"/api/v1/tasks/{task['id']}/approvals")).json()
    assert approvals, "email.send requested approval"
    aid = next(a for a in approvals if a["status"] == "pending")["id"]
    await client.post(
        f"/api/v1/tasks/{task['id']}/approvals/{aid}/decision", json={"approve": True}
    )
    await client.post(f"/api/v1/tasks/{task['id']}/run", json={"resume": True})

    drafts = (await client.get("/api/v1/drafts")).json()
    assert drafts, "draft was persisted"
    assert drafts[0]["status"] == "drafted", "refusal does not consume the draft"
    events = (await client.get(f"/api/v1/tasks/{task['id']}/events")).json()["events"]
    refused = [e for e in events if e["event_type"] == "email.send_refused"]
    assert refused and refused[-1]["payload"]["reason"] == "no_connected_service"


@pytest.mark.asyncio
async def test_approval_gate_then_canned_send(
    client, session, dev_user, factory, monkeypatch, smtp_connection
):
    """The full honest path: draft -> approval gate -> user decision ->
    resume -> canned send with a no-network disclosure, draft marked sent,
    and an audit record. Also: the send approval BOUND to the exact content."""
    from app.services import agent_service

    await seed_xp(session, dev_user, 100)
    monkeypatch.setattr(
        agent_service, "make_chat_client", lambda settings: ScriptedClient(email_plan())
    )
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Send digest", "budget_xp": 20}
        )
    ).json()
    resp = await client.post(f"/api/v1/tasks/{task['id']}/run")
    assert resp.status_code == 202
    body = (await client.get(f"/api/v1/tasks/{task['id']}")).json()
    assert body["status"] == "awaiting_approval"

    # The pending approval carries an expiry (binding content AND time).
    approvals = (await client.get(f"/api/v1/tasks/{task['id']}/approvals")).json()
    send_approval = next(a for a in approvals if "email.send" in a["action_type"])
    assert send_approval["status"] == "pending"
    assert send_approval["expires_at"] is not None

    decided = await client.post(
        f"/api/v1/tasks/{task['id']}/approvals/{send_approval['id']}/decision",
        json={"approve": True},
    )
    assert decided.status_code == 200

    resumed = await client.post(
        f"/api/v1/tasks/{task['id']}/run", json={"resume": True}
    )
    assert resumed.status_code == 202
    body = (await client.get(f"/api/v1/tasks/{task['id']}")).json()
    assert body["status"] == "completed"

    drafts = (await client.get("/api/v1/drafts")).json()
    assert drafts[0]["status"] == "sent"
    assert drafts[0]["provider_mode"] == "canned"
    assert drafts[0]["connection_id"] == smtp_connection["id"]

    events = (await client.get(f"/api/v1/tasks/{task['id']}/events")).json()["events"]
    sent = [e for e in events if e["event_type"] == "email.sent"]
    assert sent, "email.sent event recorded"
    assert "no network transmission" in sent[-1]["payload"]["disclosure"]

    # Resending the same content without a new draft is refused (the sent
    # draft can never be sent again).
    plan2 = {
        "plan": [
            {
                "step": 1,
                "tool": "email.send",
                "why": "again",
                "arguments": {
                    "to": "client@example.test",
                    "subject": "Weekly research digest",
                    "body": "Findings from this week's research, as approved.",
                },
            }
        ],
        "estimated_xp": 2,
        "deliverable": "resent",
    }
    monkeypatch.setattr(
        agent_service, "make_chat_client", lambda settings: ScriptedClient(plan2)
    )
    task2 = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Resend digest", "budget_xp": 20}
        )
    ).json()
    await client.post(f"/api/v1/tasks/{task2['id']}/run")
    approvals2 = (await client.get(f"/api/v1/tasks/{task2['id']}/approvals")).json()
    aid2 = next(a for a in approvals2 if a["status"] == "pending")["id"]
    await client.post(
        f"/api/v1/tasks/{task2['id']}/approvals/{aid2}/decision", json={"approve": True}
    )
    await client.post(f"/api/v1/tasks/{task2['id']}/run", json={"resume": True})
    events2 = (await client.get(f"/api/v1/tasks/{task2['id']}/events")).json()["events"]
    assert any(
        e["event_type"] == "email.send_refused"
        and "no unsent draft" in json.dumps(e["payload"])
        for e in events2
    ), "a sent draft cannot be silently resent"


@pytest.mark.asyncio
async def test_expired_pending_approval_cannot_be_approved(
    client, session, dev_user, factory, monkeypatch, smtp_connection
):
    """Approval binding #2: the time window. A pending approval past its
    expiry cannot be approved — the runner will request a fresh one."""
    from app.services import agent_service

    await seed_xp(session, dev_user, 100)
    monkeypatch.setattr(
        agent_service, "make_chat_client", lambda settings: ScriptedClient(email_plan())
    )
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Send digest", "budget_xp": 20}
        )
    ).json()
    await client.post(f"/api/v1/tasks/{task['id']}/run")
    approvals = (await client.get(f"/api/v1/tasks/{task['id']}/approvals")).json()
    send_approval = next(a for a in approvals if "email.send" in a["action_type"])

    row = await session.get(Approval, send_approval["id"])
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    decided = await client.post(
        f"/api/v1/tasks/{task['id']}/approvals/{send_approval['id']}/decision",
        json={"approve": True},
    )
    assert decided.status_code == 409
    session.expire_all()
    row = await session.get(Approval, send_approval["id"])
    assert row.status == "expired"


@pytest.mark.asyncio
async def test_stale_approved_approval_re_requests(
    client, session, dev_user, factory, monkeypatch, smtp_connection
):
    """An approval granted long ago does not authorize a later execution:
    the resume path expires it and requests a fresh decision."""
    from app.services import agent_service

    await seed_xp(session, dev_user, 100)
    monkeypatch.setattr(
        agent_service, "make_chat_client", lambda settings: ScriptedClient(email_plan())
    )
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Send digest", "budget_xp": 20}
        )
    ).json()
    await client.post(f"/api/v1/tasks/{task['id']}/run")
    approvals = (await client.get(f"/api/v1/tasks/{task['id']}/approvals")).json()
    send_approval = next(a for a in approvals if "email.send" in a["action_type"])
    await client.post(
        f"/api/v1/tasks/{task['id']}/approvals/{send_approval['id']}/decision",
        json={"approve": True},
    )

    row = await session.get(Approval, send_approval["id"])
    row.approved_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()

    await client.post(f"/api/v1/tasks/{task['id']}/run", json={"resume": True})
    session.expire_all()
    approvals = (await client.get(f"/api/v1/tasks/{task['id']}/approvals")).json()
    statuses = {a["id"]: a["status"] for a in approvals}
    assert statuses[send_approval["id"]] == "expired"
    fresh = [a for a in approvals if a["status"] == "pending"]
    assert fresh, "a fresh approval was requested after the stale one expired"
    # nothing was sent
    drafts = (await client.get("/api/v1/drafts")).json()
    assert drafts[0]["status"] == "drafted"


# -- schedule grammar -----------------------------------------------------------------


def test_parse_schedule_valid():
    s = automation_core.parse_schedule("every 30m")
    assert s.kind == "every" and s.seconds == 1800
    assert automation_core.parse_schedule("hourly").seconds == 3600
    d = automation_core.parse_schedule("daily 09:30")
    assert (d.hour, d.minute) == (9, 30)
    assert automation_core.parse_schedule("daily").hour == 0


def test_parse_schedule_refuses_garbage():
    for expr in [
        "every 10s",
        "weekly on monday",
        "0 9 * * *",
        "",
        "every 0m",
        "daily 25:00",
    ]:
        with pytest.raises(automation_core.ScheduleError):
            automation_core.parse_schedule(expr)


def test_next_run_after_deterministic():
    base = datetime(2026, 10, 15, 10, 0, 0)
    assert automation_core.next_run_after("every 1h", base) == datetime(
        2026, 10, 15, 11, 0, 0
    )
    assert automation_core.next_run_after("daily 09:30", base) == datetime(
        2026, 10, 16, 9, 30, 0
    )
    assert automation_core.next_run_after(
        "daily 09:30", datetime(2026, 10, 15, 8, 0)
    ) == datetime(2026, 10, 15, 9, 30, 0)


# -- jobs API: lifecycle + validation ---------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_validation(client, session, dev_user):
    bad_schedule = await client.post(
        "/api/v1/jobs",
        json={"objective": "x", "schedule": "weekly", "budget_per_run_xp": 5},
    )
    assert bad_schedule.status_code == 422
    over_cap = await client.post(
        "/api/v1/jobs",
        json={
            "objective": "x",
            "schedule": "hourly",
            "budget_per_run_xp": get_settings().automation_max_budget_per_run_xp + 1,
        },
    )
    assert over_cap.status_code == 422
    bad_conditions = await client.post(
        "/api/v1/jobs",
        json={
            "objective": "x",
            "schedule": "hourly",
            "budget_per_run_xp": 5,
            "conditions": {"notify_on_telegram_spam": True},
        },
    )
    assert bad_conditions.status_code == 422

    ok = await client.post(
        "/api/v1/jobs",
        json={
            "objective": "Monitor supplier prices",
            "schedule": "daily 09:30",
            "budget_per_run_xp": 20,
            "budget_total_xp": 200,
            "conditions": {"notify_on": ["run_failed"], "balance_below_xp": 100},
        },
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["status"] == "active"
    assert body["next_run_at"] is not None
    assert body["conditions"] == {"balance_below_xp": 100, "notify_on": ["run_failed"]}


@pytest.mark.asyncio
async def test_pause_resume_cancel_lifecycle(client, session, dev_user):
    job = (
        await client.post(
            "/api/v1/jobs",
            json={"objective": "Monitor", "schedule": "hourly", "budget_per_run_xp": 5},
        )
    ).json()

    paused = await client.post(f"/api/v1/jobs/{job['id']}/pause")
    assert paused.json()["status"] == "paused"
    pause_twice = await client.post(f"/api/v1/jobs/{job['id']}/pause")
    assert pause_twice.status_code == 409

    resumed = await client.post(f"/api/v1/jobs/{job['id']}/resume")
    assert resumed.json()["status"] == "active"
    assert resumed.json()["next_run_at"] is not None

    cancelled = await client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    cancel_twice = await client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert cancel_twice.status_code == 409
    trigger_cancelled = await client.post(f"/api/v1/jobs/{job['id']}/run")
    assert trigger_cancelled.status_code == 409


@pytest.mark.asyncio
async def test_job_ownership_enforced(client, session, dev_user):
    job = (
        await client.post(
            "/api/v1/jobs",
            json={
                "objective": "Private monitoring",
                "schedule": "hourly",
                "budget_per_run_xp": 5,
            },
        )
    ).json()
    _other, token = await make_second_user(session)
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/jobs", headers=headers)).json() == []
    assert (
        await client.get(f"/api/v1/jobs/{job['id']}", headers=headers)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/jobs/{job['id']}/pause", headers=headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/jobs/{job['id']}/runs", headers=headers)
    ).status_code == 404


# -- sweep: budgets, failure policy, approval wait ---------------------------------------


def make_executor(
    outcome: str = "completed", charge: int = 0, attempts: dict | None = None
):
    """Deterministic automation executor: drives the spawned task to a state."""

    async def _execute(factory, task_id, settings, resume: bool = False):
        if attempts is not None:
            attempts[task_id] = attempts.get(task_id, 0) + 1
        async with factory() as s:
            task = await s.get(Task, task_id)
            if outcome == "completed":
                task.status = "completed"
                task.actual_xp = charge
                await ledger.settle_task(
                    s,
                    user_id=task.user_id,
                    task_id=task.id,
                    reserved_xp=task.reserved_xp,
                    actual_xp=charge,
                    idempotency_key=f"autoexec:{task.id}",
                )
                task.reserved_xp = 0
            elif outcome == "awaiting_approval":
                task.status = "awaiting_approval"
                s.add(
                    Approval(
                        user_id=task.user_id,
                        task_id=task.id,
                        action_type="tool.email.send",
                        action_digest="deadbeef" * 8,
                        status="pending",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
            else:
                task.status = "failed"
                task.error = "injected failure"
                await ledger.release_reservation(
                    s,
                    user_id=task.user_id,
                    task_id=task.id,
                    amount=task.reserved_xp,
                    idempotency_key=f"autoexec-fail:{task.id}",
                )
                task.reserved_xp = 0
            await s.commit()
        return {"status": outcome}

    return _execute


async def make_job(session, dev_user, settings, **kwargs) -> ScheduledJob:
    now = datetime(2026, 10, 15, 9, 0, 0)
    job, _disc = await automation_core.create_job(
        session,
        user_id=dev_user.id,
        objective=kwargs.pop("objective", "Monitor suppliers"),
        schedule=kwargs.pop("schedule", "every 1h"),
        budget_per_run_xp=kwargs.pop("budget_per_run_xp", 20),
        settings=settings,
        now=now,
        **kwargs,
    )
    await session.commit()
    job.next_run_at = now  # due immediately
    await session.commit()
    return job


@pytest.mark.asyncio
async def test_sweep_executes_due_job_and_records_history(
    session, dev_user, factory, settings
):
    await seed_xp(session, dev_user, 100)
    job = await make_job(session, dev_user, settings)
    run = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=15),
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    assert run.status == "succeeded"
    assert run.xp_charged == 15
    assert run.trigger == "scheduled"
    await session.refresh(job)
    assert job.total_spent_xp == 15
    assert job.run_count == 1
    assert job.last_run_status == "succeeded"
    assert job.consecutive_failures == 0
    assert job.next_run_at == datetime(2026, 10, 15, 10, 0, 0)

    history = (
        (
            await session.execute(
                select(AutomationRun).where(AutomationRun.job_id == job.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1

    # Sweep API returns the outcome compactly.
    outcomes = await automation_core.run_due_jobs(
        session,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=5),
        now=datetime(2026, 10, 15, 10, 0, 0),
    )
    assert outcomes and outcomes[0]["status"] == "succeeded"
    await session.refresh(job)
    assert job.total_spent_xp == 20
    assert job.run_count == 2


@pytest.mark.asyncio
async def test_per_run_budget_is_the_task_cap(session, dev_user, factory, settings):
    """The spawned task's budget IS the per-run cap: the ledger refuses any
    settlement beyond it, so per-run XP limits hold end-to-end."""
    await seed_xp(session, dev_user, 100)
    job = await make_job(session, dev_user, settings, budget_per_run_xp=5)

    async def greedy(factory, task_id, settings, resume=False):
        async with factory() as s:
            task = await s.get(Task, task_id)
            task.status = "completed"
            task.actual_xp = 10  # over the 5 XP cap
            with pytest.raises(ledger.LedgerError):
                await ledger.settle_task(
                    s,
                    user_id=task.user_id,
                    task_id=task.id,
                    reserved_xp=task.reserved_xp,
                    actual_xp=10,
                )
            task.status = "failed"
            task.error = "settlement refused over cap"
            await ledger.release_reservation(
                s,
                user_id=task.user_id,
                task_id=task.id,
                amount=task.reserved_xp,
                idempotency_key=f"greedy:{task.id}",
            )
            task.reserved_xp = 0
            await s.commit()
        return {"status": "failed"}

    run = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=greedy,
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    assert run.status == "failed"
    assert run.xp_charged == 0
    await session.refresh(job)
    assert job.total_spent_xp == 0
    balance = await ledger.get_or_create_account(session, dev_user.id)
    assert balance.balance == 100, "nothing was charged beyond the cap"


@pytest.mark.asyncio
async def test_total_budget_exhausted_auto_pauses(session, dev_user, factory, settings):
    await seed_xp(session, dev_user, 100)
    job = await make_job(
        session, dev_user, settings, budget_per_run_xp=10, budget_total_xp=10
    )
    await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=10),
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    await session.refresh(job)
    assert job.total_spent_xp == 10

    run2 = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=10),
        now=datetime(2026, 10, 15, 10, 0, 0),
    )
    assert run2.status == "skipped_total_budget"
    await session.refresh(job)
    assert job.status == "paused"
    assert job.auto_paused_reason == "budget_total_exhausted"
    from xp_core.models.entities import Notification

    notes = (
        (
            await session.execute(
                select(Notification).where(Notification.user_id == dev_user.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(n.kind == "automation.auto_paused" for n in notes)


@pytest.mark.asyncio
async def test_consecutive_failures_auto_pause(session, dev_user, factory, settings):
    await seed_xp(session, dev_user, 100)
    settings.automation_max_consecutive_failures = 2
    job = await make_job(session, dev_user, settings)
    failing = make_executor(outcome="failed")

    await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=failing,
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    await session.refresh(job)
    assert job.status == "active" and job.consecutive_failures == 1

    await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=failing,
        now=datetime(2026, 10, 15, 10, 0, 0),
    )
    await session.refresh(job)
    assert job.status == "paused"
    assert "consecutive_failures" in (job.auto_paused_reason or "")
    from xp_core.models.entities import Notification

    notes = (
        (
            await session.execute(
                select(Notification).where(Notification.user_id == dev_user.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(n.kind == "automation.auto_paused" for n in notes)


@pytest.mark.asyncio
async def test_blocked_run_waits_for_approval_then_resumes(
    session, dev_user, factory, settings
):
    """The spawned task needs a user decision: the run blocks, subsequent
    sweeps WAIT (no silent repeat, no new approval spam), and after approval
    the SAME task is resumed."""
    await seed_xp(session, dev_user, 100)
    attempts: dict[str, int] = {}
    job = await make_job(session, dev_user, settings)
    blocking = make_executor(outcome="awaiting_approval", attempts=attempts)

    run1 = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=blocking,
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    assert run1.status == "blocked_on_approval"
    assert run1.task_id is not None

    # Subsequent sweep while pending: waits, creates NO new run/task.
    outcome = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=blocking,
        now=datetime(2026, 10, 15, 10, 0, 0),
    )
    assert outcome.id == run1.id
    runs = (
        (
            await session.execute(
                select(AutomationRun).where(AutomationRun.job_id == job.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(runs) == 1
    assert sum(attempts.values()) == 1, "consequential action not repeated"

    # User approves -> next sweep resumes the SAME task.
    approval = (
        await session.execute(select(Approval).where(Approval.task_id == run1.task_id))
    ).scalar_one()
    approval.status = "approved"
    approval.approved_at = datetime.now(UTC)
    await session.commit()

    final = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=15, attempts=attempts),
        now=datetime(2026, 10, 15, 11, 0, 0),
    )
    assert final.id == run1.id
    assert final.status == "succeeded"
    assert sum(attempts.values()) == 2  # original + resume, nothing more


@pytest.mark.asyncio
async def test_denied_approval_fails_run_without_repeat(
    session, dev_user, factory, settings
):
    await seed_xp(session, dev_user, 100)
    attempts: dict[str, int] = {}
    job = await make_job(session, dev_user, settings)
    blocking = make_executor(outcome="awaiting_approval", attempts=attempts)
    run1 = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=blocking,
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    approval = (
        await session.execute(select(Approval).where(Approval.task_id == run1.task_id))
    ).scalar_one()
    approval.status = "denied"
    approval.revoked_at = datetime.now(UTC)
    await session.commit()

    run2 = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=blocking,
        now=datetime(2026, 10, 15, 10, 0, 0),
    )
    assert run2.status == "failed"
    assert "denied" in (run2.error or "")
    task = await session.get(Task, run1.task_id)
    assert task.status == "failed"
    balance = await ledger.get_or_create_account(session, dev_user.id)
    assert balance.balance == 100, "reservation fully released"
    await session.refresh(job)
    assert job.consecutive_failures == 1


@pytest.mark.asyncio
async def test_insufficient_balance_skips(session, dev_user, factory, settings):
    job = await make_job(session, dev_user, settings)  # no XP seeded
    ran = {"calls": 0}

    async def _exec(factory, task_id, settings, resume=False):
        ran["calls"] += 1
        return {"status": "completed"}

    run = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=_exec,
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    assert run.status == "skipped_budget"
    assert ran["calls"] == 0


@pytest.mark.asyncio
async def test_sweep_skips_paused_and_cancelled(session, dev_user, factory, settings):
    ran = {"calls": 0}

    async def _exec(factory, task_id, settings, resume=False):
        ran["calls"] += 1
        return {"status": "completed"}

    now = datetime(2026, 10, 15, 9, 0, 0)
    paused_job, _ = await automation_core.create_job(
        session,
        user_id=dev_user.id,
        objective="paused",
        schedule="every 1h",
        budget_per_run_xp=5,
        settings=settings,
        now=now,
    )
    paused_job.status = "paused"
    paused_job.next_run_at = now
    cancelled_job, _ = await automation_core.create_job(
        session,
        user_id=dev_user.id,
        objective="cancelled",
        schedule="every 1h",
        budget_per_run_xp=5,
        settings=settings,
        now=now,
    )
    cancelled_job.status = "cancelled"
    cancelled_job.next_run_at = now
    await session.commit()

    outcomes = await automation_core.run_due_jobs(
        session, settings, session_factory=factory, execute_task=_exec, now=now
    )
    assert outcomes == []
    assert ran["calls"] == 0


@pytest.mark.asyncio
async def test_stale_running_run_recovered(session, dev_user, factory, settings):
    """A worker crash mid-run leaves the run 'running'; after the stale
    window it is marked failed and the failure ladder applies."""
    settings.automation_run_stale_seconds = 60
    await seed_xp(session, dev_user, 100)
    job = await make_job(session, dev_user, settings)

    # Simulate a crash: run row created but never finalized.
    task = Task(
        user_id=dev_user.id, objective="Monitor", status="planned", budget_xp=20
    )
    session.add(task)
    await session.flush()
    run = AutomationRun(
        job_id=job.id,
        user_id=dev_user.id,
        run_number=1,
        trigger="scheduled",
        status="running",
        task_id=task.id,
        xp_budget_per_run=20,
        started_at=datetime(2026, 10, 15, 8, 0, 0),
    )
    session.add(run)
    job.run_count = 1
    await session.commit()

    # Fresh crash (30s old, window 60s): sweep waits, does not run concurrently.
    outcome = await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=5),
        now=datetime(2026, 10, 15, 8, 0, 30),
    )
    assert outcome.status == "running"

    # Stale (70s old): marked failed; next sweep proceeds normally.
    await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="completed", charge=5),
        now=datetime(2026, 10, 15, 8, 1, 10),
    )
    # Verify via a FRESH session: the sweep interleaved two sessions on the
    # shared test connection, and expired-instance refresh paths on the
    # sweep session are a StaticPool test artifact (Postgres/worker: separate
    # pooled connections, no such artifact).
    async with factory() as verify:
        stale = (
            await verify.execute(
                select(AutomationRun).where(AutomationRun.id == run.id)
            )
        ).scalar_one()
        assert stale.status == "failed"
        assert "worker restart" in (stale.error or "")


# -- notifications ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_notifications_and_read(
    client, session, dev_user, factory, settings
):
    await seed_xp(session, dev_user, 30)
    job = await make_job(
        session,
        dev_user,
        settings,
        budget_per_run_xp=10,
        conditions={
            "notify_on": ["run_failed", "run_succeeded"],
            "balance_below_xp": 50,
        },
    )
    # A failed run -> run_failed notification; balance 20 < 50 -> balance_below.
    await automation_core.process_job(
        session,
        job,
        settings,
        session_factory=factory,
        execute_task=make_executor(outcome="failed"),
        now=datetime(2026, 10, 15, 9, 0, 0),
    )
    listed = (await client.get("/api/v1/notifications")).json()
    kinds = [n["kind"] for n in listed["notifications"]]
    assert "automation.run_failed" in kinds
    assert "automation.balance_below" in kinds
    assert listed["unread"] == len(listed["notifications"])

    nid = listed["notifications"][0]["id"]
    read = await client.post(f"/api/v1/notifications/{nid}/read")
    assert read.json()["read_at"] is not None
    again = await client.post(f"/api/v1/notifications/{nid}/read")
    assert again.status_code == 200  # idempotent

    _other, token = await make_second_user(session)
    others = await client.get(
        "/api/v1/notifications", headers={"Authorization": f"Bearer {token}"}
    )
    assert others.json()["notifications"] == []
    foreign = await client.post(
        f"/api/v1/notifications/{nid}/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert foreign.status_code == 404


# -- real SMTP provider against a loopback server (empirical proof) -------------------


class _LoopbackSMTPServer:
    """Minimal asyncio SMTP server: enough protocol for smtplib to deliver.

    Refuse recipients matching 'reject@' to prove the definite-refusal path.
    """

    def __init__(self) -> None:
        self.received: list[bytes] = []
        self.server = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        def line(data: bytes, text: str) -> None:
            writer.write(data)
            writer.write(b"\r\n")

        writer.write(b"220 loopback ESMTP\r\n")
        await writer.drain()
        envelope: list[str] = []
        data_mode = False
        buffer = b""
        while True:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=5)
            except TimeoutError:
                break
            if not raw:
                break
            if data_mode:
                if raw.strip() == b".":
                    self.received.append(buffer)
                    writer.write(b"250 OK queued\r\n")
                    await writer.drain()
                    data_mode = False
                    buffer = b""
                else:
                    buffer += raw
                continue
            cmd = raw.strip().decode(errors="replace")
            upper = cmd.upper()
            if upper.startswith("EHLO") or upper.startswith("HELO"):
                writer.write(b"250-loopback\r\n250-AUTH PLAIN\r\n250 SMTPUTF8\r\n")
            elif upper.startswith("MAIL FROM"):
                envelope.append(cmd)
                writer.write(b"250 OK\r\n")
            elif upper.startswith("RCPT TO"):
                if "reject@" in cmd.lower():
                    writer.write(b"550 5.1.1 recipient refused\r\n")
                else:
                    envelope.append(cmd)
                    writer.write(b"250 OK\r\n")
            elif upper.startswith("DATA"):
                if any("reject@" in e.lower() for e in envelope):
                    writer.write(b"554 no valid recipients\r\n")
                else:
                    writer.write(b"354 go ahead\r\n")
                    data_mode = True
            elif upper.startswith("AUTH"):
                writer.write(b"235 2.7.0 Accepted\r\n")
            elif upper.startswith("QUIT"):
                writer.write(b"221 bye\r\n")
                await writer.drain()
                break
            else:
                writer.write(b"250 OK\r\n")
            await writer.drain()
        writer.close()


@pytest.mark.asyncio
async def test_smtp_provider_delivers_and_refuses_definitely():
    from email_adapter import SmtpEmailProvider

    server = _LoopbackSMTPServer()
    port = await server.start()
    try:
        provider = SmtpEmailProvider(timeout_seconds=5)
        credential = {
            "host": "127.0.0.1",
            "port": port,
            "username": "agent@example.test",
            "password": "pw",
            "starttls": False,
        }
        ok = await provider.send(
            to="client@example.test",
            subject="Hi",
            body="Body",
            credential=credential,
        )
        assert ok.status == "sent"
        assert ok.is_definite
        assert server.received and b"Subject: Hi" in server.received[0]

        refused = await provider.send(
            to="reject@example.test",
            subject="Hi",
            body="Body",
            credential=credential,
        )
        assert refused.status == "refused"
        assert "definite refusal" in refused.disclosure
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_smtp_provider_unknown_outcome_on_dead_server():
    """A server that accepts the connection then VANISHES mid-session is an
    UNCERTAIN outcome: the disclosure says the system will not auto-retry."""
    from email_adapter import SmtpEmailProvider

    async def _black_hole(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            writer.write(b"220 blackhole ESMTP\r\n")
            await writer.drain()
            await asyncio.wait_for(reader.readline(), timeout=2)  # client EHLO
            # ...and the server disappears without answering.
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(_black_hole, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        provider = SmtpEmailProvider(timeout_seconds=1)
        outcome = await provider.send(
            to="client@example.test",
            subject="Hi",
            body="Body",
            credential={
                "host": "127.0.0.1",
                "port": port,
                "username": "a@b.c",
                "password": "pw",
                "starttls": False,
            },
        )
        assert outcome.status == "unknown"
        assert "NOT" in outcome.disclosure and "retry" in outcome.disclosure
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_canned_provider_discloses_no_network():
    from email_adapter import get_email_provider

    settings = get_settings()
    outcome = await get_email_provider(settings).send(
        to="x@y.z", subject="s", body="b", credential=None
    )
    assert outcome.status == "sent"
    assert "no network transmission" in outcome.disclosure
    assert outcome.provider == "canned"
