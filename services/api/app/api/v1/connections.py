"""External service connections (phase 9): link, list, revoke.

Acceptance coverage: "External actions require valid authorization and
approved scope" + "Users can revoke connected services". Credentials are
Fernet-encrypted at rest with the operator master key; NO response ever
contains a secret — the vault is the single decryption path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from xp_core.config import Settings, get_settings
from xp_core.models.entities import ConnectedService
from xp_core.schemas.api import ConnectionCreateIn, ConnectionOut
from xp_core.services import vault

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/connections", tags=["connections"])


def _out(connection: ConnectedService, disclosure: str | None = None) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        provider=connection.provider,
        scopes=list(connection.scopes or []),
        status=connection.status,
        credential_reference=connection.credential_reference,
        created_at=connection.created_at,
        revoked_at=connection.revoked_at,
        disclosure=disclosure,
    )


@router.get("/providers")
async def list_providers() -> dict:
    """Published capability surface: what can be linked, and which scopes
    each provider unlocks. Unknown providers are refused at link time."""
    return {
        "providers": vault.provider_info(),
        "disclosure": (
            "credentials are encrypted at rest; only the linked user's agent "
            "actions may use a connection, within the scopes granted here"
        ),
    }


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def link_connection(
    payload: ConnectionCreateIn, user: CurrentUser, session: DbSession
) -> ConnectionOut:
    settings: Settings = get_settings()
    try:
        connection, disclosure = await vault.link_connection(
            session,
            user_id=user.id,
            provider=payload.provider,
            scopes=payload.scopes,
            payload=payload.credential,
            settings=settings,
        )
    except vault.ConnectionError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await session.commit()
    await session.refresh(connection)
    return _out(connection, disclosure)


@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    user: CurrentUser, session: DbSession, include_revoked: bool = False
) -> list[ConnectionOut]:
    rows = await vault.list_connections(
        session, user.id, include_revoked=include_revoked
    )
    return [_out(row) for row in rows]


@router.delete("/{connection_id}", response_model=ConnectionOut)
async def revoke_connection(
    connection_id: str, user: CurrentUser, session: DbSession
) -> ConnectionOut:
    connection = await vault.get_owned_connection(session, user.id, connection_id)
    if connection is None or connection.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="connection not found"
        )
    provider = connection.provider
    revoked = await vault.revoke_connection(session, user.id, connection_id)
    if not revoked:  # pragma: no cover - guarded above
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="connection not found"
        )
    await session.commit()
    await session.refresh(connection)
    return _out(
        connection,
        disclosure=(
            f"{provider} connection revoked; its stored credential was deleted, "
            "so agent email sends will refuse until a new connection is linked"
        ),
    )
