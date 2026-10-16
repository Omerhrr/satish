"""Shared FastAPI dependencies: DB session + current-user resolution."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import get_settings
from xp_core.db import get_session
from xp_core.logging import get_logger, request_id_var
from xp_core.models.entities import AuditEvent, User
from xp_core.services.ratelimit import IdentityCache
from xp_core.services.security import get_or_create_dev_user, resolve_user_from_token

log = get_logger(__name__)

SettingsDep = Annotated[object, Depends(get_settings)]


async def current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller.

    - Bearer session token when provided (Mini App / bot).
    - Dev user when DEV_MODE and no credentials - local/sandbox convenience.
    """
    settings = get_settings()
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        user = await resolve_user_from_token(session, token)
        if user is not None:
            # Validation-joined rate-limit keys (KL-09): every successfully
            # validated bearer feeds the limiter's identity cache so ALL valid
            # tokens of one user share ONE bucket, regardless of rotation.
            cache = getattr(request.app.state, "identity_cache", None)
            if cache is not None:
                cache.remember(token, user.id)
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


def _presented_operator_credential(request: Request) -> tuple[str | None, str]:
    """Extract the operator credential: X-Operator-Token first, then an
    Authorization bearer. Returns (credential-or-None, source)."""
    explicit = request.headers.get("x-operator-token", "").strip()
    if explicit:
        return explicit, "x-operator-token"
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip(), "bearer"
    return None, "none"


async def require_operator(
    session: DbSession, request: Request
) -> None:
    """Real access control for /ops/* (KL-11 closure).

    Decision table (honest, in order):
    - Credential configured: REQUIRED everywhere, dev included (an operator
      who sets a token wants it enforced); constant-time compared; every
      grant and every denial is audited, never with the credential itself.
    - No credential + DEV_MODE: allowed (local/sandbox convenience).
    - No credential + non-dev: 503 - the surfaces stay DARK rather than open.
      A missing operator setup must never silently become public access.
    """
    settings = get_settings()
    expected = settings.ops_operator_token
    if expected:
        presented, source = _presented_operator_credential(request)
        path = request.url.path
        if presented is None or not hmac.compare_digest(
            presented.encode("utf-8"), expected.encode("utf-8")
        ):
            session.add(
                AuditEvent(
                    actor_type="admin",
                    actor_id=None,
                    event_type="ops.access_denied",
                    resource_type="ops",
                    resource_id=path,
                    request_id=request_id_var.get(),
                    metadata_redacted={
                        "method": request.method,
                        "source": source,
                        "reason": "missing" if presented is None else "invalid",
                        "credential_fingerprint": (
                            IdentityCache.fingerprint(presented) if presented else None
                        ),
                    },
                )
            )
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="operator authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        session.add(
            AuditEvent(
                actor_type="admin",
                event_type="ops.access_granted",
                resource_type="ops",
                resource_id=path,
                request_id=request_id_var.get(),
                metadata_redacted={"method": request.method, "source": source},
            )
        )
        await session.commit()
        return
    if settings.dev_mode:
        return
    log.warning(
        "ops_refused_unconfigured",
        path=request.url.path,
        method=request.method,
        mode="dark_until_configured",
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "operator access is not configured on this deployment; "
            "ops surfaces refuse to open instead of serving unauthenticated"
        ),
    )


OperatorGate = Annotated[None, Depends(require_operator)]
