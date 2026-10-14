"""Authentication: Telegram initData exchange + logout + me."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from xp_core.config import get_settings
from xp_core.schemas.api import SessionOut, UserOut
from xp_core.services.security import (
    create_session,
    get_or_create_dev_user,
    get_or_create_user_from_telegram,
    verify_telegram_init_data,
)

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthIn(BaseModel):
    init_data: str = Field(default="", max_length=8192)


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
    token, _row = await create_session(session, user.id, settings)
    await session.commit()
    return SessionOut(
        session_token=token,
        user=UserOut(id=user.id, display_name=user.display_name, status=user.status, created_at=user.created_at),
        mode=mode,  # type: ignore[arg-type]
    )


@router.post("/logout")
async def logout() -> dict[str, str]:
    # Session revocation lands with the session-store hardening in phase 2;
    # the client drops the token, which is sufficient for the scaffold.
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    """Return the authenticated caller's profile (api_contract: GET /me)."""
    return UserOut(
        id=user.id, display_name=user.display_name, status=user.status, created_at=user.created_at
    )
