"""Condition-based notifications (phase 9): list + mark read.

Persisted by backend condition evaluation (xp_core.services.automation).
The Telegram relay (xp_core.services.relay + telegram-adapter) records its
one push decision per notification in relay_status; the API discloses it
but never pretends a push happened when it did not.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from xp_core.models.entities import Notification
from xp_core.schemas.api import NotificationOut, NotificationsPageOut

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        kind=row.kind,
        payload=row.payload,
        job_id=row.job_id,
        run_id=row.run_id,
        read_at=row.read_at,
        relay_status=row.relay_status,
        created_at=row.created_at,
    )


@router.get("", response_model=NotificationsPageOut)
async def list_notifications(
    user: CurrentUser, session: DbSession, limit: int = 50
) -> NotificationsPageOut:
    limit = max(1, min(limit, 200))
    rows = (
        (
            await session.execute(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    unread = (
        await session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalar_one()
    return NotificationsPageOut(
        notifications=[_out(row) for row in rows],
        unread=int(unread),
    )


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: str, user: CurrentUser, session: DbSession
) -> NotificationOut:
    row = (
        await session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="notification not found"
        )
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
    return _out(row)
