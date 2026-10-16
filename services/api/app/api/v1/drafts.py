"""Email drafts (phase 9): preview surface for the Mini App.

Drafts are created by the agent's email.draft tool. The preview endpoint is
owner-checked; the send path lives in the tool registry behind the approval
gate - this router is read-only by design.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from xp_core.models.entities import EmailDraft
from xp_core.schemas.api import EmailDraftOut

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _out(draft: EmailDraft) -> EmailDraftOut:
    return EmailDraftOut(
        id=draft.id,
        task_id=draft.task_id,
        connection_id=draft.connection_id,
        to_address=draft.to_address,
        subject=draft.subject,
        body=draft.body,
        digest=draft.digest,
        status=draft.status,
        provider_mode=draft.provider_mode,
        error=draft.error,
        sent_at=draft.sent_at,
        created_at=draft.created_at,
    )


@router.get("", response_model=list[EmailDraftOut])
async def list_drafts(
    user: CurrentUser, session: DbSession, limit: int = 50
) -> list[EmailDraftOut]:
    limit = max(1, min(limit, 200))
    rows = (
        (
            await session.execute(
                select(EmailDraft)
                .where(EmailDraft.user_id == user.id)
                .order_by(EmailDraft.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_out(row) for row in rows]


@router.get("/{draft_id}", response_model=EmailDraftOut)
async def get_draft(
    draft_id: str, user: CurrentUser, session: DbSession
) -> EmailDraftOut:
    draft = (
        await session.execute(
            select(EmailDraft).where(
                EmailDraft.id == draft_id, EmailDraft.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="draft not found"
        )
    return _out(draft)
