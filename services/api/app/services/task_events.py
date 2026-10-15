"""Task event stream primitives (shared by agent runtime + research tools).

Extracted from agent_service so product tool handlers can append events
without a circular import (agent_service -> research_tools -> events).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.models.entities import TaskEvent


async def _next_seq(session: AsyncSession, task_id: str) -> int:
    current = (
        await session.execute(
            select(func.coalesce(func.max(TaskEvent.seq), 0)).where(
                TaskEvent.task_id == task_id
            )
        )
    ).scalar_one()
    return int(current) + 1


async def append_event(
    session: AsyncSession, task_id: str, event_type: str, payload: dict[str, Any] | None
) -> TaskEvent:
    row = TaskEvent(
        task_id=task_id,
        seq=await _next_seq(session, task_id),
        event_type=event_type,
        payload=payload or {},
    )
    session.add(row)
    await session.flush()
    return row


async def load_events(session: AsyncSession, task_id: str) -> list[TaskEvent]:
    rows = await session.execute(
        select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.seq)
    )
    return list(rows.scalars())


__all__ = ["append_event", "load_events"]
