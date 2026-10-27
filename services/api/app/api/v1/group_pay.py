"""Pay and split bills in Telegram groups.

Bot: "/pay ₦2000 @musa lunch" or "/split ₦10000 @ada @musa dinner" in a group
-> POST /group/create (bot key) -> the bot posts a card with a "Pay in
Satish" button (a Mini App link with start param gp_<id>). Whoever taps it
pays from their own wallet; the Mini App then reports POST /group/{id}/paid
and the card is updated to tick them off.

Amounts can be sats ("500") or any currency ("₦2000", "2000 ngn", "$5"),
converted at the current rate when the card is made.
"""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from xp_core.config import get_settings
from xp_core.logging import get_logger
from xp_core.models.entities import GroupPayment, TelegramAccount, WalletHandle
from xp_core.services.security import TelegramIdentity, get_or_create_user_from_telegram

from app.api.v1.device_link import bot_key
from app.api.v1.money import fmt_money
from app.deps import CurrentUser, DbSession

log = get_logger(__name__)
router = APIRouter(prefix="/group", tags=["group"])

SYMBOLS = {"₦": "NGN", "$": "USD", "€": "EUR", "£": "GBP", "₵": "GHS", "R": "ZAR"}
_AMOUNT = re.compile(r"^(?P<sym>[₦$€£₵])?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<k>[kKmM])?\s*(?P<code>[A-Za-z]{3}|sats?)?$")


def parse_amount(text: str) -> tuple[float, str] | None:
    """'₦2,000' -> (2000, 'NGN'); '5usd' -> (5, 'USD'); '500' -> (500, 'SAT'); '2k ngn' -> (2000, 'NGN')."""
    m = _AMOUNT.match((text or "").strip())
    if not m:
        return None
    n = float(m.group("num").replace(",", ""))
    if m.group("k"):
        n *= 1_000 if m.group("k").lower() == "k" else 1_000_000
    code = m.group("code")
    if m.group("sym"):
        cur = SYMBOLS[m.group("sym")]
    elif code and not code.lower().startswith("sat"):
        cur = code.upper()
    else:
        cur = "SAT"
    return (n, cur) if n > 0 else None


async def to_sats(amount: float, cur: str) -> int | None:
    if cur == "SAT":
        return int(round(amount))
    from app.api.v1.price import current_rates

    rate = (await current_rates()).get("btc", {}).get(cur)  # type: ignore[union-attr]
    return int(round(amount / rate * 1e8)) if rate else None


async def satish_username(session, telegram_or_satish: str) -> str | None:
    """A Telegram @mention or a Satish @username -> the Satish username to pay."""
    name = telegram_or_satish.lstrip("@").lower()
    net = get_settings().onchain_network
    h = await session.scalar(
        select(WalletHandle.username).where(
            func.lower(WalletHandle.username) == name, WalletHandle.network == net, WalletHandle.status == "active"
        )
    )
    if h:
        return h
    uid = await session.scalar(select(TelegramAccount.user_id).where(func.lower(TelegramAccount.username) == name))
    if not uid:
        return None
    return await session.scalar(
        select(WalletHandle.username).where(WalletHandle.user_id == uid, WalletHandle.network == net, WalletHandle.status == "active")
    )


def card_text(g: GroupPayment) -> str:
    sats = f"{g.amount_sats:,} sats"
    note = f" for {g.note}" if g.note else ""
    paid = g.paid or {}
    if g.kind == "pay":
        head = f"💸 Payment to @{g.to_username}: {g.display} ({sats}){note}"
        tail = "\n✅ Paid" if paid else "\nTap below to pay it from your Satish wallet."
        return head + tail
    lines = [f"🧾 Split{note}: {g.display} each ({sats}) to @{g.to_username}"]
    for p in g.participants or []:
        lines.append(f"{'✅' if p.lower() in {k.lower() for k in paid} else '⬜'} @{p}")
    done = sum(1 for p in g.participants or [] if p.lower() in {k.lower() for k in paid})
    lines.append(f"\n{done} of {len(g.participants or [])} paid. Tap below to pay your share.")
    return "\n".join(lines)


class CreateIn(BaseModel):
    kind: str = Field(pattern="^(pay|split)$")
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    amount: str = Field(min_length=1, max_length=32)
    to: str | None = None  # pay: who gets paid
    participants: list[str] = Field(default_factory=list, max_length=30)  # split
    note: str | None = Field(default=None, max_length=140)
    chat_id: int | None = None


@router.post("/create")
async def create(payload: CreateIn, session: DbSession, x_bot_key: str = Header(default="")) -> dict:
    s = get_settings()
    if not s.telegram_bot_token or not hmac.compare_digest(x_bot_key, bot_key(s.telegram_bot_token)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bot only")
    parsed = parse_amount(payload.amount)
    if not parsed:
        return {"status": "bad_amount"}
    creator = await get_or_create_user_from_telegram(
        session,
        TelegramIdentity(payload.telegram_user_id, payload.username, payload.first_name, int(datetime.now(UTC).timestamp())),
    )
    amount, cur = parsed
    if payload.kind == "pay":
        if not payload.to:
            return {"status": "no_recipient"}
        to = await satish_username(session, payload.to)
        if not to:
            return {"status": "unknown_user", "who": payload.to.lstrip("@")}
        per, people = amount, []
    else:
        people = list(dict.fromkeys(p.lstrip("@") for p in payload.participants if p.strip()))
        if not people:
            return {"status": "no_people"}
        own = await session.scalar(
            select(WalletHandle.username).where(
                WalletHandle.user_id == creator.id, WalletHandle.network == s.onchain_network, WalletHandle.status == "active"
            )
        )
        if not own:
            return {"status": "no_username"}
        to = own
        # The splitter's own share isn't collected: total / (people + 1).
        mine = (payload.username or "").lower()
        people = [p for p in people if p.lower() != mine]
        per = amount / (len(people) + 1)
    sats = await to_sats(per, cur)
    if not sats or sats < 1:
        return {"status": "no_rate"}
    display = f"{int(per):,} sats" if cur == "SAT" else fmt_money(per, cur)
    g = GroupPayment(
        id=secrets.token_urlsafe(8)[:10].replace("-", "x").replace("_", "y"),
        kind=payload.kind,
        creator_user_id=creator.id,
        to_username=to,
        amount_sats=sats,
        display=display,
        note=(payload.note or "").strip() or None,
        participants=people or None,
        paid={},
        chat_id=payload.chat_id,
    )
    session.add(g)
    await session.commit()
    return {"status": "ok", "id": g.id, "text": card_text(g), "start_param": f"gp_{g.id}"}


class MessageIn(BaseModel):
    message_id: int


@router.post("/{gid}/message")
async def set_message(gid: str, payload: MessageIn, session: DbSession, x_bot_key: str = Header(default="")) -> dict:
    s = get_settings()
    if not s.telegram_bot_token or not hmac.compare_digest(x_bot_key, bot_key(s.telegram_bot_token)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bot only")
    g = await session.get(GroupPayment, gid)
    if g:
        g.message_id = payload.message_id
        await session.commit()
    return {"status": "ok"}


class GroupOut(BaseModel):
    id: str
    kind: str
    to_username: str
    amount_sats: int
    display: str
    note: str | None
    already_paid: bool


async def _who(session, user_id: str) -> str:
    tg = await session.scalar(select(TelegramAccount.username).where(TelegramAccount.user_id == user_id))
    return (tg or user_id[:8]).lower()


@router.get("/{gid}", response_model=GroupOut)
async def get_group(gid: str, user: CurrentUser, session: DbSession) -> GroupOut:
    g = await session.get(GroupPayment, gid)
    if g is None:
        raise HTTPException(404, "This payment card no longer exists.")
    me = await _who(session, user.id)
    return GroupOut(id=g.id, kind=g.kind, to_username=g.to_username, amount_sats=g.amount_sats, display=g.display,
                    note=g.note, already_paid=me in {k.lower() for k in (g.paid or {})})


class PaidIn(BaseModel):
    ref: str = Field(min_length=4, max_length=128)  # txid or Lightning payment id


@router.post("/{gid}/paid")
async def mark_paid(gid: str, payload: PaidIn, user: CurrentUser, session: DbSession) -> dict:
    g = await session.get(GroupPayment, gid)
    if g is None:
        raise HTTPException(404, "This payment card no longer exists.")
    me = await _who(session, user.id)
    paid = dict(g.paid or {})
    paid[me] = payload.ref
    g.paid = paid
    await session.commit()
    await _edit_card(g)
    return {"status": "ok"}


async def _edit_card(g: GroupPayment) -> None:
    s = get_settings()
    if not (s.telegram_bot_token and g.chat_id and g.message_id):
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{s.telegram_bot_token}/editMessageText",
                json={
                    "chat_id": g.chat_id,
                    "message_id": g.message_id,
                    "text": card_text(g),
                    "reply_markup": {"inline_keyboard": [[{"text": "💸 Pay in Satish", "url": f"{s.mini_app_url}?startapp=gp_{g.id}"}]]},
                },
            )
    except httpx.HTTPError as exc:
        log.info("group_card_edit_failed", error=type(exc).__name__)
