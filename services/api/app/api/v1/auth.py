"""Authentication: Telegram initData exchange + session lifecycle.

Phase-2 hardening: logout performs server-side revocation, users can list
and individually revoke their active sessions, sessions are short-lived
(trust boundary control), and ownership is enforced everywhere - a session
id that belongs to somebody else is indistinguishable from a missing one.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from xp_core.config import get_settings
from xp_core.schemas.api import SessionInfoOut, SessionOut, UserOut
from xp_core.services.security import (
    create_session,
    get_or_create_dev_user,
    get_or_create_user_from_telegram,
    list_active_sessions,
    resolve_user_from_token,
    revoke_session_by_id,
    revoke_session_by_token,
    verify_telegram_init_data,
)

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthIn(BaseModel):
    init_data: str = Field(default="", max_length=8192)


def _require_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer session token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1].strip()


@router.post("/telegram", response_model=SessionOut)
async def auth_telegram(payload: TelegramAuthIn, session: DbSession) -> SessionOut:
    """Exchange Telegram Mini App initData for an application session.

    In DEV_MODE an empty/invalid payload yields the local dev user so the
    scaffold is explorable. In staging+ this endpoint strictly validates.
    """
    settings = get_settings()
    identity = None
    if payload.init_data and settings.telegram_bot_token:
        identity = verify_telegram_init_data(
            payload.init_data,
            settings.telegram_bot_token,
            max_age_seconds=settings.telegram_init_data_max_age_seconds,
        )
        if identity is None and not settings.dev_mode:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or stale initData"
            )
    if identity is not None:
        user = await get_or_create_user_from_telegram(session, identity)
        mode = "telegram"
    else:
        if not settings.dev_mode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="init_data required"
            )
        user = await get_or_create_dev_user(session)
        mode = "dev"
    token, _row = await create_session(session, user.id, settings, created_via=mode)
    await session.commit()
    return SessionOut(
        session_token=token,
        user=UserOut(id=user.id, display_name=user.display_name, status=user.status, created_at=user.created_at),
        mode=mode,  # type: ignore[arg-type]
    )


@router.post("/logout")
async def logout(
    session: DbSession,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Revoke the presented session server-side (phase-2 hardening).

    Requires a bearer token even in DEV_MODE: there is nothing to revoke
    otherwise, and pretending otherwise would hide bugs.
    """
    token = _require_bearer(authorization)
    # The presented token must still resolve; a stale/forged token gets 401
    # so clients can distinguish "already logged out" from "never was".
    user = await resolve_user_from_token(session, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    revoked = await revoke_session_by_token(session, token)
    await session.commit()
    return {"status": "logged_out", "revoked": revoked}


@router.get("/sessions", response_model=list[SessionInfoOut])
async def sessions(user: CurrentUser, session: DbSession) -> list[SessionInfoOut]:
    """List the caller's live sessions (session lifecycle deliverable)."""
    rows = await list_active_sessions(session, user.id)
    return [
        SessionInfoOut(
            id=row.id,
            created_via=row.created_via,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, object]:
    """Revoke one of the caller's own sessions by id (ownership enforced)."""
    revoked = await revoke_session_by_id(session, user.id, session_id)
    if not revoked:
        # Same answer for "not yours" and "doesn't exist" - no oracle.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    await session.commit()
    return {"status": "revoked", "session_id": session_id}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    """Return the authenticated caller's profile (api_contract: GET /me)."""
    return UserOut(
        id=user.id, display_name=user.display_name, status=user.status, created_at=user.created_at
    )
