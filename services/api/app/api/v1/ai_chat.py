"""Satish AI as a chat: memory the user controls, and the endpoint the
Telegram bot calls when someone messages it directly.

Bot flow: a private message (not a command) -> POST /ai/chat (bot key) ->
a task in that person's chat thread runs on the AI worker -> the answer is
sent back to the chat by telegram_delivery, like any other task.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from xp_core.config import get_settings
from xp_core.logging import get_logger
from xp_core.models.entities import AiMemory, ChatTurn, Task
from xp_core.services import ledger
from xp_core.services.security import TelegramIdentity, get_or_create_user_from_telegram

from app.api.v1.device_link import bot_key
from app.deps import CurrentUser, DbSession
from app.services import ai_memory

log = get_logger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


class MemoryOut(BaseModel):
    id: str
    text: str
    source: str
    created_at: datetime


class MemoryIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)


@router.get("/memory", response_model=list[MemoryOut])
async def get_memory(user: CurrentUser, session: DbSession) -> list[MemoryOut]:
    return [MemoryOut(id=m.id, text=m.text, source=m.source, created_at=m.created_at) for m in await ai_memory.list_memories(session, user.id)]


@router.post("/memory", response_model=list[MemoryOut])
async def add_memory(payload: MemoryIn, user: CurrentUser, session: DbSession) -> list[MemoryOut]:
    await ai_memory.add_memory(session, user.id, payload.text, source="user")
    await session.commit()
    return await get_memory(user, session)


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_one(memory_id: str, user: CurrentUser, session: DbSession) -> None:
    await session.execute(delete(AiMemory).where(AiMemory.id == memory_id, AiMemory.user_id == user.id))
    await session.commit()


@router.delete("/memory", status_code=status.HTTP_204_NO_CONTENT)
async def forget_all(user: CurrentUser, session: DbSession) -> None:
    await session.execute(delete(AiMemory).where(AiMemory.user_id == user.id))
    await session.execute(delete(ChatTurn).where(ChatTurn.user_id == user.id))
    await session.commit()


class ChatIn(BaseModel):
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    language_code: str | None = None
    text: str = Field(min_length=1, max_length=12000)  # question (+ text of an attached file)
    command: str | None = None  # "forget" | "new"


@router.post("/chat")
async def chat(payload: ChatIn, session: DbSession, x_bot_key: str = Header(default="")) -> dict:
    s = get_settings()
    if not s.telegram_bot_token or not hmac.compare_digest(x_bot_key, bot_key(s.telegram_bot_token)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bot only")
    user = await get_or_create_user_from_telegram(
        session,
        TelegramIdentity(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            first_name=payload.first_name,
            auth_date=int(datetime.now(UTC).timestamp()),
        ),
    )
    await ledger.grant_welcome(session, user_id=user.id, amount=s.tk_welcome_bonus)
    thread = f"tg-{payload.telegram_user_id}"

    if payload.command == "forget":
        await session.execute(delete(AiMemory).where(AiMemory.user_id == user.id))
        await session.execute(delete(ChatTurn).where(ChatTurn.user_id == user.id))
        await session.commit()
        return {"status": "forgotten"}
    if payload.command == "new":
        await session.execute(delete(ChatTurn).where(ChatTurn.thread_id == thread))
        await session.commit()
        return {"status": "new_chat"}

    fact = ai_memory.remembered_fact(payload.text)
    if fact:
        await ai_memory.add_memory(session, user.id, fact, source="user")
        await session.commit()
        return {"status": "remembered", "fact": fact}

    busy = await session.scalar(
        select(Task.id).where(Task.thread_id == thread, Task.status.in_(("running", "planned"))).limit(1)
    )
    if busy:
        return {"status": "busy"}
    balance = (await ledger.get_or_create_account(session, user.id)).balance
    budget = min(balance, s.agent_auto_budget_xp)
    if budget <= 0:
        await session.commit()
        return {"status": "no_tk"}

    task = Task(
        user_id=user.id,
        objective=payload.text,
        status="planned",
        budget_xp=budget,
        language=ai_memory.language_from_code(payload.language_code),
        thread_id=thread,
    )
    session.add(task)
    await session.flush()
    await ledger.reserve_budget(session, user_id=user.id, task_id=task.id, amount=budget)
    task.reserved_xp = budget
    await ai_memory.add_turn(session, user.id, thread, "user", payload.text)
    task.status = "running"
    task.queued_at = datetime.now(UTC).replace(tzinfo=None)
    await session.commit()

    from app.worker_bridge import enqueue_agent_task_job

    await enqueue_agent_task_job(task_id=task.id, resume=False)
    return {"status": "started", "task_id": task.id}
