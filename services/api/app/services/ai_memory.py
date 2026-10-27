"""Satish AI memory and Telegram chat threads.

- Memories: short facts about a user ("lives in Kaduna", "sells phone
  accessories", "prefers answers in Hausa"). Saved automatically after a chat
  answer (the model proposes at most a few durable facts) or when the user
  says "remember ...". Users see and delete them in the app; /forget in the
  bot clears all of them.
- Chat turns: the last few messages of a Telegram conversation, kept for
  24 hours only, so "and in Abuja?" makes sense. Telegram holds the history.

Memories and turns are context for the model only; they never become
instructions and are never shared with anyone else.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.logging import get_logger
from xp_core.models.entities import AiMemory, ChatTurn, Task

log = get_logger(__name__)

MAX_MEMORIES = 40
TURN_TTL = timedelta(hours=24)
TURNS_IN_CONTEXT = 8

TELEGRAM_LANGS = {
    "en": "English", "ha": "Hausa", "yo": "Yoruba", "ig": "Igbo", "pcm": "Nigerian Pidgin", "fr": "French",
    "ar": "Arabic", "sw": "Swahili", "pt": "Portuguese", "es": "Spanish", "am": "Amharic", "zu": "Zulu",
    "de": "German", "it": "Italian", "ru": "Russian", "tr": "Turkish", "hi": "Hindi", "zh": "Chinese",
    "id": "Indonesian", "nl": "Dutch", "uk": "Ukrainian", "fa": "Persian", "so": "Somali", "rw": "Kinyarwanda",
}

_REMEMBER = re.compile(r"^\s*(please\s+)?remember( that)?\s+(?P<fact>.{3,280})$", re.I)


def language_from_code(code: str | None) -> str | None:
    return TELEGRAM_LANGS.get((code or "").lower().split("-")[0]) if code else None


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


async def list_memories(session: AsyncSession, user_id: str) -> list[AiMemory]:
    rows = await session.execute(
        select(AiMemory).where(AiMemory.user_id == user_id).order_by(AiMemory.created_at.desc()).limit(MAX_MEMORIES)
    )
    return list(rows.scalars())


async def add_memory(session: AsyncSession, user_id: str, text: str, source: str = "user") -> AiMemory | None:
    text = " ".join((text or "").split())[:300]
    if len(text) < 3:
        return None
    existing = [m.text.lower() for m in await list_memories(session, user_id)]
    if text.lower() in existing:
        return None
    row = AiMemory(user_id=user_id, text=text, source=source)
    session.add(row)
    await session.flush()
    # Keep the newest MAX_MEMORIES.
    old = (
        await session.execute(
            select(AiMemory.id).where(AiMemory.user_id == user_id).order_by(AiMemory.created_at.desc()).offset(MAX_MEMORIES)
        )
    ).scalars().all()
    if old:
        await session.execute(delete(AiMemory).where(AiMemory.id.in_(old)))
    return row


def remembered_fact(text: str) -> str | None:
    """'remember I live in Kaduna' -> 'I live in Kaduna'."""
    m = _REMEMBER.match(text or "")
    return m.group("fact").strip().rstrip(".") if m else None


async def add_turn(session: AsyncSession, user_id: str, thread_id: str, role: str, text: str) -> None:
    session.add(ChatTurn(user_id=user_id, thread_id=thread_id, role=role, text=(text or "")[:4000]))
    await session.execute(delete(ChatTurn).where(ChatTurn.created_at < _naive(datetime.now(UTC) - TURN_TTL)))


async def context_for(session: AsyncSession, task: Task) -> str | None:
    parts: list[str] = []
    mems = await list_memories(session, task.user_id)
    if mems:
        parts.append("Things the user asked Satish to remember:\n" + "\n".join(f"- {m.text}" for m in reversed(mems)))
    if task.thread_id:
        since = _naive(datetime.now(UTC) - TURN_TTL)
        turns = (
            await session.execute(
                select(ChatTurn)
                .where(ChatTurn.thread_id == task.thread_id, ChatTurn.created_at >= since)
                .order_by(ChatTurn.created_at.desc())
                .limit(TURNS_IN_CONTEXT + 1)
            )
        ).scalars().all()
        # The newest user turn is this task's own question; leave it out.
        earlier = [t for t in reversed(turns)][:-1] if turns and turns[0].role == "user" else list(reversed(turns))
        if earlier:
            parts.append(
                "Earlier in this chat (use it to understand follow-up questions):\n"
                + "\n".join(f"{'User' if t.role == 'user' else 'Satish'}: {t.text[:700]}" for t in earlier[-TURNS_IN_CONTEXT:])
            )
    return "\n\n".join(parts) or None


async def learn_from_chat(session: AsyncSession, client, user_id: str, question: str, answer: str) -> int:
    """Ask the model for at most 3 durable facts about the user in this
    exchange (location, business, preferences). Returns how many were saved."""
    prompt = (
        "From this exchange, list at most 3 lasting facts about the USER that would help answer their future "
        "questions (where they live, their work or business, preferences, people or things they care about). "
        "Only facts the user stated about themselves. No facts from the answer or the web. No sensitive data "
        "(passwords, keys, health, exact addresses, account numbers). Reply as JSON: "
        '{"facts": ["...", "..."]} or {"facts": []}.\n\n'
        f"User: {question[:1500]}\nSatish: {answer[:1500]}"
    )
    try:
        out = await client.complete([{"role": "user", "content": prompt}], json_mode=True)
        facts = json.loads(out.get("content") or "{}").get("facts") or []
    except Exception as exc:
        log.info("memory_extract_skipped", error=type(exc).__name__)
        return 0
    saved = 0
    for f in facts[:3]:
        if isinstance(f, str) and await add_memory(session, user_id, f, source="auto"):
            saved += 1
    return saved
