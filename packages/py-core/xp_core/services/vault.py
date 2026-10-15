"""Scoped credential storage for connected external services (phase 9).

Deliverables: "External service connection framework" + "Scoped credential
storage" + "Users can revoke connected services".

Design:
- One ``ConnectedService`` row per link; exactly one ``ServiceCredential``
  row holding the Fernet-encrypted credential payload (key derived from the
  operator master key via sha256 — the master key itself is never stored).
- The plaintext never appears in logs, task events, audit metadata, or API
  responses; ``load_credential`` is the ONLY decryption path.
- Revocation hard-deletes the credential row (a revoked connection cannot
  authenticate even if other layers were bypassed) and is audited.
- In dev mode a documented fallback key keeps local development zero-config;
  the fallback is disclosed on every surface. Non-dev environments refuse to
  link connections until ``XP_CONNECTIONS_CREDENTIAL_KEY`` is configured —
  silently encrypting with a shipped constant would be fake security.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import AuditEvent, ConnectedService, ServiceCredential

log = get_logger(__name__)

DEV_FALLBACK_KEY = "xp-dev-credential-fallback-key-do-not-use-outside-dev"
DEV_DISCLOSURE = (
    "credentials encrypted with the documented DEV fallback key "
    "(XP_CONNECTIONS_CREDENTIAL_KEY unset); dev mode only"
)

# Provider allowlist: what may be linked and which tool scopes it unlocks.
# Unknown providers are refused — never stored-and-ignored.
PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "smtp": {
        "label": "SMTP email sending",
        "scopes": ["email:draft", "email:send"],
        "required_fields": ["host", "port", "username", "password"],
        "optional_fields": ["starttls"],
    },
}
_SECRET_FIELDS = {"password"}


class ConnectionError(Exception):
    """Link/load/refuse failures with an honest, disclosable reason."""


def _fernet(settings: Settings) -> tuple[Fernet, str | None]:
    """Return (fernet, disclosure). Disclosure is set when the dev fallback is in use."""
    master = settings.connections_credential_key
    if master is None:
        if not settings.dev_mode:
            raise ConnectionError(
                "XP_CONNECTIONS_CREDENTIAL_KEY is not configured; refusing to "
                "handle credentials outside dev mode"
            )
        master = DEV_FALLBACK_KEY
        return Fernet(
            base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest())
        ), (DEV_DISCLOSURE)
    return Fernet(
        base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest())
    ), None


def encrypt_payload(payload: dict[str, Any], settings: Settings) -> str:
    f, _ = _fernet(settings)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f.encrypt(canonical.encode()).decode()


def decrypt_payload(ciphertext: str, settings: Settings) -> dict[str, Any]:
    f, _ = _fernet(settings)
    try:
        raw = f.decrypt(ciphertext.encode())
    except InvalidToken as exc:  # wrong key or tampered row
        raise ConnectionError(
            "credential decryption failed (wrong master key?)"
        ) from exc
    return json.loads(raw.decode())


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Metadata-safe view: secret fields replaced by presence markers."""
    return {k: ("***" if k in _SECRET_FIELDS else v) for k, v in payload.items()}


def provider_info() -> dict[str, Any]:
    """Published capability surface for the connections UI."""
    return {
        provider: {
            "label": spec["label"],
            "scopes": spec["scopes"],
            "required_fields": spec["required_fields"],
            "optional_fields": spec["optional_fields"],
        }
        for provider, spec in PROVIDER_SPECS.items()
    }


def _validate_credential(provider: str, payload: dict[str, Any]) -> None:
    spec = PROVIDER_SPECS.get(provider)
    if spec is None:
        raise ConnectionError(f"unknown provider: {provider}")
    missing = [field for field in spec["required_fields"] if not payload.get(field)]
    if missing:
        raise ConnectionError(f"missing credential fields: {', '.join(missing)}")
    if not isinstance(payload.get("port", 0), int):
        raise ConnectionError("port must be an integer")


async def link_connection(
    session: AsyncSession,
    *,
    user_id: str,
    provider: str,
    scopes: list[str] | None,
    payload: dict[str, Any],
    settings: Settings,
) -> tuple[ConnectedService, str | None]:
    """Link a service and store its credential encrypted at rest.

    Returns (connection, disclosure). Scopes are intersected with the
    provider allowlist — a link can never grant a scope the provider does
    not define.
    """
    _validate_credential(provider, payload)
    spec = PROVIDER_SPECS[provider]
    granted = sorted(set(scopes or spec["scopes"]) & set(spec["scopes"]))
    if not granted:
        raise ConnectionError("no valid scopes requested")

    f, disclosure = _fernet(settings)
    del f  # encryption happens inside encrypt_payload
    connection = ConnectedService(
        user_id=user_id,
        provider=provider,
        scopes=granted,
        status="linked",
    )
    session.add(connection)
    await session.flush()

    cred = ServiceCredential(
        connection_id=connection.id,
        ciphertext=encrypt_payload(payload, settings),
        key_version=1,
    )
    session.add(cred)
    await session.flush()

    connection.credential_reference = f"vault:{cred.id}"
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user_id,
            event_type="connection.linked",
            resource_type="connected_service",
            resource_id=connection.id,
            metadata_redacted={
                "provider": provider,
                "scopes": granted,
                "credential_fields": sorted(redact_payload(payload).keys()),
            },
        )
    )
    await session.flush()
    log.info(
        "connection_linked",
        user_id=user_id,
        connection_id=connection.id,
        provider=provider,
        dev_fallback=disclosure is not None,
    )
    return connection, disclosure


async def get_owned_connection(
    session: AsyncSession, user_id: str, connection_id: str
) -> ConnectedService | None:
    return (
        await session.execute(
            select(ConnectedService).where(
                ConnectedService.id == connection_id,
                ConnectedService.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def list_connections(
    session: AsyncSession, user_id: str, *, include_revoked: bool = False
) -> list[ConnectedService]:
    rows = (
        (
            await session.execute(
                select(ConnectedService)
                .where(ConnectedService.user_id == user_id)
                .order_by(ConnectedService.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if include_revoked:
        return list(rows)
    return [r for r in rows if r.status != "revoked"]


async def load_credential(
    session: AsyncSession, connection: ConnectedService, settings: Settings
) -> dict[str, Any]:
    """The single decryption path. Revoked connections never decrypt."""
    if connection.status == "revoked":
        raise ConnectionError("connection revoked")
    row = (
        await session.execute(
            select(ServiceCredential).where(
                ServiceCredential.connection_id == connection.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ConnectionError("no credential stored for connection")
    return decrypt_payload(row.ciphertext, settings)


async def revoke_connection(
    session: AsyncSession, user_id: str, connection_id: str
) -> bool:
    """Revoke one of the caller's connections; hard-delete its credential.

    Idempotent semantics: revoking an unknown or already-revoked connection
    returns False (the API surfaces 404 rather than pretending success).
    """
    connection = await get_owned_connection(session, user_id, connection_id)
    if connection is None or connection.status == "revoked":
        return False
    await session.execute(
        delete(ServiceCredential).where(
            ServiceCredential.connection_id == connection.id
        )
    )
    connection.status = "revoked"
    connection.revoked_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user_id,
            event_type="connection.revoked",
            resource_type="connected_service",
            resource_id=connection.id,
            metadata_redacted={"provider": connection.provider},
        )
    )
    await session.flush()
    log.info(
        "connection_revoked",
        user_id=user_id,
        connection_id=connection.id,
        provider=connection.provider,
    )
    return True


async def find_active_connection(
    session: AsyncSession, user_id: str, provider: str, scope: str
) -> ConnectedService | None:
    """The linked, non-revoked connection that unlocks ``scope`` — or None."""
    spec = PROVIDER_SPECS.get(provider)
    if spec is None or scope not in spec["scopes"]:
        return None
    rows = (
        (
            await session.execute(
                select(ConnectedService).where(
                    ConnectedService.user_id == user_id,
                    ConnectedService.provider == provider,
                    ConnectedService.status == "linked",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if scope in set(row.scopes or []):
            return row
    return None
