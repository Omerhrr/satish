"""Security helpers: Telegram init-data validation + session token handling.

The Mini App sends Telegram initData; the SERVER validates it (architecture
security_notes: reject forged or stale authentication payloads). Seed phrases
or private keys are never requested here — Telegram is an interface, not a
key vault.

Phase-2 hardening: short-lived sessions, server-side revocation (logout,
per-session revoke), and last-used tracking for the session lifecycle UI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings, get_settings
from xp_core.db import new_id
from xp_core.logging import get_logger
from xp_core.models.entities import Session, TelegramAccount, User

log = get_logger(__name__)


@dataclass(slots=True)
class TelegramIdentity:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    auth_date: int


def verify_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
    now: int | None = None,
) -> TelegramIdentity | None:
    """Validate Telegram WebApp initData per the official algorithm.

    Returns a typed identity, or None when the payload is forged or stale.
    """
    try:
        pairs = dict(
            item.split("=", 1) for item in init_data.split("&") if "=" in item
        )
    except ValueError:
        return None

    received_hash = pairs.pop("hash", None)
    auth_date_raw = pairs.get("auth_date")  # stays in the check string!
    if not received_hash or not auth_date_raw:
        return None

    # data_check_string: sorted key=value lines of all fields except hash
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        log.warning("telegram_init_data_rejected", reason="bad_hash")
        return None

    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        return None
    now_ts = now if now is not None else int(time.time())
    if now_ts - auth_date > max_age_seconds:
        log.warning("telegram_init_data_rejected", reason="stale", age=now_ts - auth_date)
        return None

    try:
        user_obj = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    if not user_obj.get("id"):
        return None

    return TelegramIdentity(
        telegram_user_id=int(user_obj["id"]),
        username=user_obj.get("username"),
        first_name=user_obj.get("first_name"),
        auth_date=auth_date,
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    session: AsyncSession,
    user_id: str,
    settings: Settings | None = None,
    *,
    created_via: str = "miniapp",
) -> tuple[str, Session]:
    """Issue a short-lived bearer session; only the SHA-256 hash is persisted."""
    s = settings or get_settings()
    token = new_id() + new_id().replace("-", "")
    expires = datetime.now(UTC) + timedelta(hours=max(1, s.session_ttl_hours))
    row = Session(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=expires,
        created_via=created_via,
    )
    session.add(row)
    await session.flush()
    return token, row


DEV_USER_TELEGRAM_ID = 90_000_001


async def get_or_create_dev_user(session: AsyncSession) -> User:
    """Dev-mode convenience user so the scaffold is explorable without Telegram."""
    user = (
        await session.execute(
            select(User).join(TelegramAccount, TelegramAccount.user_id == User.id).where(
                TelegramAccount.telegram_user_id == DEV_USER_TELEGRAM_ID
            )
        )
    ).scalar_one_or_none()
    if user is not None:
        return user
    user = User(display_name="Dev User")
    session.add(user)
    await session.flush()
    session.add(
        TelegramAccount(
            user_id=user.id,
            telegram_user_id=DEV_USER_TELEGRAM_ID,
            username="dev_user",
        )
    )
    await session.flush()
    log.info("dev_user_created", user_id=user.id)
    return user


# Write-amplification guard: refresh last_used_at at most once per window.
LAST_USED_REFRESH_SECONDS = 300


async def resolve_user_from_token(session: AsyncSession, token: str) -> User | None:
    row = (
        await session.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None
    now = datetime.now(UTC)
    last_used = row.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=UTC)
    if last_used is None or (now - last_used).total_seconds() >= LAST_USED_REFRESH_SECONDS:
        row.last_used_at = now
    return (
        await session.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()


# -- session lifecycle (phase 2: "Session lifecycle and logout") ---------------


async def revoke_session_by_token(session: AsyncSession, token: str) -> bool:
    """Revoke the session matching a raw bearer token. False if already gone."""
    row = (
        await session.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    log.info("session_revoked", session_id=row.id, by="logout")
    return True


async def revoke_session_by_id(
    session: AsyncSession, user_id: str, session_id: str
) -> bool:
    """Revoke one of the caller's own sessions by id — ownership enforced."""
    row = (
        await session.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    log.info("session_revoked", session_id=row.id, by="owner")
    return True


async def list_active_sessions(session: AsyncSession, user_id: str) -> list[Session]:
    """The caller's live sessions (not revoked, not expired), newest first."""
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .order_by(Session.created_at.desc())
        )
    ).scalars().all()
    live: list[Session] = []
    for row in rows:
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires >= now:
            live.append(row)
    return live


async def get_or_create_user_from_telegram(
    session: AsyncSession, identity: TelegramIdentity
) -> User:
    account = (
        await session.execute(
            select(TelegramAccount).where(
                TelegramAccount.telegram_user_id == identity.telegram_user_id
            )
        )
    ).scalar_one_or_none()
    if account is not None:
        user = (
            await session.execute(select(User).where(User.id == account.user_id))
        ).scalar_one()
        return user
    user = User(display_name=identity.first_name or identity.username or "Telegram User")
    session.add(user)
    await session.flush()
    session.add(
        TelegramAccount(
            user_id=user.id,
            telegram_user_id=identity.telegram_user_id,
            username=identity.username,
        )
    )
    await session.flush()
    log.info("telegram_user_linked", user_id=user.id, telegram_user_id=identity.telegram_user_id)
    return user
