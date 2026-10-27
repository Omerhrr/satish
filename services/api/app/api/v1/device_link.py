"""Sign in the Satish browser extension with your Telegram account.

1. The extension calls POST /auth/link/start and shows the code (e.g.
   ``K7QF-2M9P``). It keeps the poll secret to itself.
2. The user sends ``/link K7QF-2M9P`` to the Satish bot. The bot, which knows
   the Telegram identity, calls POST /auth/link/confirm (bot-only key).
3. The extension's POST /auth/link/poll then returns a session, once.

The code only connects a Telegram account to the extension that is holding
the poll secret, so seeing someone's code on screen is not enough to sign in
as them. Codes expire after 10 minutes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from xp_core.config import get_settings
from xp_core.logging import get_logger
from xp_core.models.entities import DeviceLink
from xp_core.schemas.api import SessionOut, UserOut
from xp_core.services.security import TelegramIdentity, create_session, get_or_create_user_from_telegram

from app.deps import DbSession

log = get_logger(__name__)
router = APIRouter(prefix="/auth/link", tags=["auth"])

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
TTL = timedelta(minutes=10)


def bot_key(bot_token: str) -> str:
    """Shared secret the bot proves itself with (derived, never the token)."""
    return hashlib.sha256(f"satish-device-link|{bot_token}".encode()).hexdigest()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in (raw or "").upper() if ch in ALPHABET)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


class LinkStartOut(BaseModel):
    code: str  # shown to the user, e.g. K7QF-2M9P
    poll_token: str  # kept by the extension only
    expires_in: int
    bot_username: str | None = None


class LinkPollIn(BaseModel):
    poll_token: str = Field(min_length=20, max_length=128)


class LinkConfirmIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None


@router.post("/start", response_model=LinkStartOut)
async def start(session: DbSession) -> LinkStartOut:
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    poll = secrets.token_urlsafe(32)
    session.add(DeviceLink(code=code, poll_hash=_hash(poll), expires_at=_naive(datetime.now(UTC) + TTL)))
    await session.commit()
    s = get_settings()
    bot = getattr(s, "telegram_bot_username", None) or None
    return LinkStartOut(code=f"{code[:4]}-{code[4:]}", poll_token=poll, expires_in=int(TTL.total_seconds()), bot_username=bot)


@router.post("/confirm")
async def confirm(payload: LinkConfirmIn, session: DbSession, x_bot_key: str = Header(default="")) -> dict:
    s = get_settings()
    if not s.telegram_bot_token or not hmac.compare_digest(x_bot_key, bot_key(s.telegram_bot_token)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bot only")
    code = normalize_code(payload.code)
    now = _naive(datetime.now(UTC))
    row = await session.scalar(
        select(DeviceLink).where(DeviceLink.code == code, DeviceLink.expires_at > now, DeviceLink.linked_at.is_(None))
    )
    if row is None:
        return {"status": "not_found"}
    user = await get_or_create_user_from_telegram(
        session,
        TelegramIdentity(
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
            first_name=payload.first_name,
            auth_date=int(datetime.now(UTC).timestamp()),
        ),
    )
    from xp_core.services import ledger

    await ledger.grant_welcome(session, user_id=user.id, amount=s.tk_welcome_bonus)
    row.user_id = user.id
    row.linked_at = now
    await session.commit()
    log.info("device_linked", user_id=user.id)
    return {"status": "linked"}


@router.post("/poll", response_model=SessionOut)
async def poll(payload: LinkPollIn, session: DbSession, response: Response) -> SessionOut | Response:
    row = await session.scalar(select(DeviceLink).where(DeviceLink.poll_hash == _hash(payload.poll_token)))
    now = _naive(datetime.now(UTC))
    if row is None or row.consumed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or used code. Start again.")
    if row.linked_at is None:
        if row.expires_at <= now:
            raise HTTPException(status.HTTP_410_GONE, "The code expired. Start again.")
        return Response(status_code=status.HTTP_202_ACCEPTED)
    won = await session.execute(
        update(DeviceLink).where(DeviceLink.id == row.id, DeviceLink.consumed_at.is_(None)).values(consumed_at=now)
    )
    if not won.rowcount:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown or used code. Start again.")
    s = get_settings()
    from xp_core.models.entities import User

    user = await session.get(User, row.user_id)
    token, _ = await create_session(session, user.id, s, created_via="extension", ttl_hours=s.extension_session_ttl_hours)
    await session.commit()
    return SessionOut(
        session_token=token,
        user=UserOut(id=user.id, display_name=user.display_name, status=user.status, created_at=user.created_at),
        mode="telegram",
    )
