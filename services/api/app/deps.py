"""Shared FastAPI dependencies: DB session + current-user resolution."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import get_settings
from xp_core.db import get_session
from xp_core.models.entities import User
from xp_core.services.security import get_or_create_dev_user, resolve_user_from_token

SettingsDep = Annotated[object, Depends(get_settings)]


async def current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller.

    - Bearer session token when provided (Mini App / bot).
    - Dev user when DEV_MODE and no credentials — local/sandbox convenience.
    """
    settings = get_settings()
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        user = await resolve_user_from_token(session, token)
        if user is not None:
            # Persist the throttled last_used_at heartbeat (independent of
            # whatever the endpoint itself commits later).
            await session.commit()
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if settings.dev_mode:
        return await get_or_create_dev_user(session)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUser = Annotated[User, Depends(current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
