"""Results go to the user's Telegram chat, then our copy is removed (D37);
users can delete one task or clear all finished ones (ledger kept)."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from xp_core.models.entities import Artifact, ResearchSource, Task, TaskEvent, TelegramAccount, XpLedgerEntry

from app.services import agent_service
from app.services.telegram_delivery import deliver_task, split_message
from tests.test_agent_runtime import ScriptedClient, scripted_stub_plan, seed_xp

pytest_plugins: list[str] = []
from tests.test_agent_runtime import client, factory  # noqa: E402,F401  (fixtures)


async def _finished_task(client, session, dev_user, monkeypatch):
    await seed_xp(session, dev_user, 100)
    monkeypatch.setattr(agent_service, "make_chat_client", lambda s: ScriptedClient(scripted_stub_plan("Rice prices")))
    task = (await client.post("/api/v1/tasks", json={"objective": "Rice prices in Kaduna", "budget_xp": 50})).json()
    body = (await client.post(f"/api/v1/tasks/{task['id']}/run")).json()
    assert body["status"] == "completed"
    return await session.get(Task, task["id"])


def test_split_message_respects_telegram_limit():
    parts = split_message(("word " * 300 + "\n\n") * 10, limit=1000)
    assert all(len(p) <= 1000 for p in parts) and len(parts) > 1


async def test_delivery_sends_answer_and_files_then_scrubs(client, session, dev_user, monkeypatch, settings):
    task = await _finished_task(client, session, dev_user, monkeypatch)
    chat = await session.scalar(select(TelegramAccount.telegram_user_id).where(TelegramAccount.user_id == dev_user.id))
    assert chat
    arts = (await session.execute(select(Artifact).where(Artifact.task_id == task.id))).scalars().all()
    assert arts, "the stub plan makes a PDF"

    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("sendDocument"):
            assert b"%PDF" in request.content
        else:
            assert f'"chat_id":{chat}'.encode() in request.content.replace(b" ", b"")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    out = await deliver_task(session, task, settings, answer="Rice is about N80,000 a bag.",
                             transport=httpx.MockTransport(handler))
    assert out == {"status": "sent", "files": len(arts)}
    assert sent[0] == "sendMessage" and "sendDocument" in sent
    await session.refresh(task)
    assert task.delivered
    for a in arts:
        await session.refresh(a)
        assert a.status == "delivered"
    done = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id,
                                                           TaskEvent.event_type == "task.completed"))).scalar_one()
    assert done.payload == {"delivered": True}
    assert not (await session.execute(select(ResearchSource).where(ResearchSource.task_id == task.id))).scalars().all()


async def test_failed_delivery_keeps_everything(client, session, dev_user, monkeypatch, settings):
    task = await _finished_task(client, session, dev_user, monkeypatch)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    out = await deliver_task(session, task, settings, answer="x",
                             transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"ok": False})))
    assert out["status"] == "failed"
    await session.refresh(task)
    assert not task.delivered


async def test_delete_and_clear_keep_the_ledger(client, session, dev_user, monkeypatch):
    task = await _finished_task(client, session, dev_user, monkeypatch)
    ledger_before = len((await session.execute(select(XpLedgerEntry))).scalars().all())
    assert (await client.delete(f"/api/v1/tasks/{task.id}")).status_code == 204
    assert all(t["id"] != task.id for t in (await client.get("/api/v1/tasks")).json())
    assert (await client.get(f"/api/v1/tasks/{task.id}")).status_code == 404
    await session.refresh(task)
    assert task.objective == "(deleted)" and task.deleted_at is not None
    assert len((await session.execute(select(XpLedgerEntry))).scalars().all()) == ledger_before

    second = (await client.post("/api/v1/tasks", json={"objective": "Another one", "budget_xp": 10})).json()
    await client.post(f"/api/v1/tasks/{second['id']}/run")
    assert (await client.post("/api/v1/tasks/clear")).json()["deleted"] == 1
    assert (await client.get("/api/v1/tasks")).json() == []
