"""Deliver a finished Satish AI task to the user's Telegram chat.

The answer goes out as messages and every file (PDF/CSV/XLSX) as a
Telegram document. Once Telegram has accepted them, the files are deleted
from our server and the task's text is scrubbed, so the user's history
lives in their Telegram chat, not with us (D37). If delivery fails nothing
is deleted and the app keeps showing the result.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import Artifact, ResearchSource, Task, TaskEvent, TelegramAccount
from dsh_adapter.runner import no_dashes
from xp_core.services.storage import LocalStorage

log = get_logger(__name__)

API = "https://api.telegram.org"
LIMIT = 3900  # Telegram's limit is 4096 characters per message


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Split on paragraph, then line, then hard boundaries."""
    text = (text or "").strip()
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def _plain(md: str) -> str:
    """Telegram plain text: drop markdown emphasis the model likes to add."""
    return md.replace("**", "").replace("__", "")


async def _chat_id(session: AsyncSession, user_id: str) -> int | None:
    return await session.scalar(
        select(TelegramAccount.telegram_user_id).where(TelegramAccount.user_id == user_id).limit(1)
    )


async def deliver_task(
    session: AsyncSession,
    task: Task,
    settings: Settings,
    *,
    answer: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    token = settings.telegram_bot_token
    if not token:
        return {"status": "skipped", "reason": "no bot token"}
    chat_id = await _chat_id(session, task.user_id)
    if chat_id is None:
        return {"status": "skipped", "reason": "no telegram account"}
    artifacts = (
        (await session.execute(select(Artifact).where(Artifact.task_id == task.id, Artifact.status == "ready")))
        .scalars()
        .all()
    )
    storage = LocalStorage(settings.artifact_dir)
    base = f"{API}/bot{token}"
    header = f"✅ Satish AI · {task.objective[:120]}"
    try:
        async with httpx.AsyncClient(timeout=60, transport=transport) as client:
            for i, chunk in enumerate(split_message(no_dashes(_plain(answer or task.deliverable or "Done.")))):
                text = f"{header}\n\n{chunk}" if i == 0 else chunk
                r = await client.post(f"{base}/sendMessage", json={"chat_id": chat_id, "text": text,
                                                                   "disable_web_page_preview": True})
                if r.status_code != 200 or not r.json().get("ok"):
                    return {"status": "failed", "reason": f"sendMessage HTTP {r.status_code}"}
            for a in artifacts:
                path = storage.open_path(a.object_key)
                if not path.is_file():
                    continue
                name = a.object_key.rsplit("/", 1)[-1]
                with path.open("rb") as fh:
                    r = await client.post(
                        f"{base}/sendDocument",
                        data={"chat_id": str(chat_id)},
                        files={"document": (name, fh, a.content_type)},
                    )
                if r.status_code != 200 or not r.json().get("ok"):
                    return {"status": "failed", "reason": f"sendDocument HTTP {r.status_code}"}
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("task_delivery_failed", task_id=task.id, error=type(exc).__name__)
        return {"status": "failed", "reason": type(exc).__name__}

    # Delivered: the history now lives in Telegram. Remove our copies.
    for a in artifacts:
        try:
            storage.open_path(a.object_key).unlink(missing_ok=True)
        except OSError:
            pass
        a.status = "delivered"
        a.size_bytes = 0
    await scrub_task(session, task)
    task.delivered = True
    await session.commit()
    return {"status": "sent", "files": len(artifacts)}


async def scrub_task(session: AsyncSession, task: Task) -> None:
    """Drop the task's content (answer, page facts, step results) but keep
    the row, its status and the TK ledger that references it."""
    events = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))).scalars().all()
    for e in events:
        if e.event_type == "task.completed":
            e.payload = {"delivered": True}
        elif e.event_type in ("research.compared", "commerce.scored", "plan.created"):
            e.payload = {}
    await session.execute(delete(ResearchSource).where(ResearchSource.task_id == task.id))
