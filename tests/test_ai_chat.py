"""Chat with Satish AI from Telegram: threads, memory, language."""

from __future__ import annotations

from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import AiMemory, ChatTurn, Task

from app.api.v1.device_link import bot_key
from app.services import agent_service, ai_memory
from tests.test_agent_runtime import ScriptedClient, client, scripted_stub_plan  # noqa: F401


def _h():
    return {"X-Bot-Key": bot_key("7000:TEST")}


async def test_chat_creates_threaded_task_in_users_language(client, session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "7000:TEST")
    started = []

    async def fake_enqueue(task_id, resume=False):
        started.append(task_id)

    import app.worker_bridge as wb

    monkeypatch.setattr(wb, "enqueue_agent_task_job", fake_enqueue)
    body = {"telegram_user_id": 7771, "first_name": "Musa", "language_code": "ha", "text": "farashin shinkafa a Kaduna?"}
    r = (await client.post("/api/v1/ai/chat", json=body, headers=_h())).json()
    assert r["status"] == "started" and started == [r["task_id"]]
    task = await session.get(Task, r["task_id"])
    assert task.language == "Hausa" and task.thread_id == "tg-7771" and task.reserved_xp == s.tk_welcome_bonus
    again = (await client.post("/api/v1/ai/chat", json=body, headers=_h())).json()
    assert again["status"] == "busy"


async def test_remember_and_forget(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "7000:TEST")
    base = {"telegram_user_id": 7772, "first_name": "Ada"}
    r = (await client.post("/api/v1/ai/chat", json={**base, "text": "Remember that I sell phone accessories in Kano"}, headers=_h())).json()
    assert r == {"status": "remembered", "fact": "I sell phone accessories in Kano"}
    mems = (await session.execute(select(AiMemory))).scalars().all()
    assert [m.text for m in mems] == ["I sell phone accessories in Kano"]
    f = (await client.post("/api/v1/ai/chat", json={**base, "text": "x", "command": "forget"}, headers=_h())).json()
    assert f["status"] == "forgotten"
    assert not (await session.execute(select(AiMemory))).scalars().all()


async def test_context_includes_memory_and_earlier_turns(session, dev_user):
    await ai_memory.add_memory(session, dev_user.id, "Lives in Kaduna")
    await ai_memory.add_turn(session, dev_user.id, "tg-1", "user", "price of rice?")
    await ai_memory.add_turn(session, dev_user.id, "tg-1", "assistant", "About N80,000 a bag.")
    await ai_memory.add_turn(session, dev_user.id, "tg-1", "user", "and in Abuja?")
    task = Task(user_id=dev_user.id, objective="and in Abuja?", budget_xp=10, thread_id="tg-1")
    ctx = await ai_memory.context_for(session, task)
    assert "Lives in Kaduna" in ctx and "About N80,000" in ctx
    assert ctx.count("and in Abuja?") == 0  # the current question isn't repeated


async def test_memory_api(client):
    assert (await client.post("/api/v1/ai/memory", json={"text": "Prefers short answers"})).status_code == 200
    mems = (await client.get("/api/v1/ai/memory")).json()
    assert mems[0]["text"] == "Prefers short answers"
    assert (await client.delete(f"/api/v1/ai/memory/{mems[0]['id']}")).status_code == 204
    assert (await client.get("/api/v1/ai/memory")).json() == []


def test_runner_answers_in_users_language():
    from dsh_adapter.runner import PlanRunner
    from dsh_adapter.tools import default_registry

    r = PlanRunner(ScriptedClient(scripted_stub_plan()), default_registry(), language="Yoruba", context="- Lives in Ibadan")
    sys_prompt = r._system()
    assert "in Yoruba" in sys_prompt and "Lives in Ibadan" in sys_prompt
    assert "in English" not in PlanRunner(ScriptedClient({}), default_registry(), language="English")._system()
