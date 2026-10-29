"""Satish for developers: API keys, payment requests over the API, webhooks.

Manage keys and webhooks from the app (signed-in session):
  GET/POST /dev/keys, DELETE /dev/keys/{id}
  GET/POST /dev/webhooks, DELETE /dev/webhooks/{id}
  POST /dev/webhooks/{id}/test, GET /dev/webhooks/{id}/deliveries

Accept bitcoin from your own server (API key: Authorization: Bearer sk_test_...):
  POST /dev/payment-requests   {amount_sats | amount + currency, note, metadata, redirect_url}
  GET  /dev/payment-requests/{id}
  GET  /dev/payment-requests
  POST /dev/payment-requests/{id}/cancel

Money always goes to a fresh address of the developer's own self-custodial
Satish wallet (their @username pool); Satish never holds it. A key can only
create and read payment requests for its owner. It can't move money or see
balances.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import get_settings
from xp_core.db import get_session
from xp_core.logging import get_logger
from xp_core.models.entities import ApiKey, PaymentRequest, User, WebhookDelivery, WebhookEndpoint
from xp_core.services import handles as svc
from xp_core.services import webhooks as wh

from app.deps import CurrentUser, DbSession, current_user

log = get_logger(__name__)
router = APIRouter(prefix="/dev", tags=["developers"])

Network = Literal["mainnet", "testnet"]
MAX_KEYS = 10
MAX_HOOKS = 5


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ------------------------------------------------------------------ keys


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    network: Network = "testnet"


class KeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    network: str
    created_at: datetime
    last_used_at: datetime | None
    secret: str | None = None  # only right after creation


def _key_out(k: ApiKey, secret: str | None = None) -> KeyOut:
    return KeyOut(id=k.id, name=k.name, prefix=k.prefix, network=k.network, created_at=k.created_at,
                  last_used_at=k.last_used_at, secret=secret)


@router.get("/keys", response_model=list[KeyOut])
async def list_keys(user: CurrentUser, session: DbSession) -> list[KeyOut]:
    rows = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None)).order_by(ApiKey.created_at.desc())
    )
    return [_key_out(k) for k in rows.scalars()]


@router.post("/keys", response_model=KeyOut, status_code=status.HTTP_201_CREATED)
async def create_key(payload: KeyIn, user: CurrentUser, session: DbSession) -> KeyOut:
    n = len((await session.execute(select(ApiKey.id).where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None)))).all())
    if n >= MAX_KEYS:
        raise HTTPException(422, f"You can have up to {MAX_KEYS} keys. Revoke one first.")
    kind = "live" if payload.network == "mainnet" else "test"
    secret = f"sk_{kind}_{secrets.token_urlsafe(30)}"
    k = ApiKey(user_id=user.id, name=payload.name.strip(), prefix=secret[:12], key_hash=_hash(secret), network=payload.network)
    session.add(k)
    await session.commit()
    return _key_out(k, secret)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: str, user: CurrentUser, session: DbSession) -> None:
    k = await session.get(ApiKey, key_id)
    if k and k.user_id == user.id and k.revoked_at is None:
        k.revoked_at = _now()
        await session.commit()


# ------------------------------------------------------------------ API-key auth


class Caller:
    def __init__(self, user: User, key: ApiKey | None):
        self.user, self.key = user, key

    @property
    def network(self) -> str | None:
        return self.key.network if self.key else None


async def api_caller(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Caller:
    """An API key (sk_test_/sk_live_) or, from the app, the signed-in session."""
    token = (authorization or "").split(" ", 1)[1].strip() if (authorization or "").lower().startswith("bearer ") else ""
    if token.startswith("sk_"):
        k = await session.scalar(select(ApiKey).where(ApiKey.key_hash == _hash(token), ApiKey.revoked_at.is_(None)))
        if k is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key.")
        user = await session.get(User, k.user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key.")
        k.last_used_at = _now()
        await session.commit()
        return Caller(user, k)
    return Caller(await current_user(session, request, authorization), None)


ApiCaller = Annotated[Caller, Depends(api_caller)]


# ------------------------------------------------------------------ payment requests


class PayReqIn(BaseModel):
    amount_sats: int | None = Field(default=None, ge=546)
    amount: float | None = Field(default=None, gt=0)  # with currency, e.g. 5000 NGN
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    note: str | None = Field(default=None, max_length=140)
    metadata: dict[str, Any] | None = None  # your order id etc., returned in webhooks
    redirect_url: str | None = Field(default=None, max_length=500)  # where the pay page sends people after paying
    network: Network | None = None  # defaults to the key's network

    @field_validator("metadata")
    @classmethod
    def small(cls, v: dict | None) -> dict | None:
        import json

        if v is not None and len(json.dumps(v)) > 2000:
            raise ValueError("metadata must be under 2,000 characters")
        return v

    @field_validator("redirect_url")
    @classmethod
    def https_only(cls, v: str | None) -> str | None:
        if v and not v.startswith("https://"):
            raise ValueError("redirect_url must start with https://")
        return v


def _links(req: PaymentRequest) -> dict[str, str]:
    s = get_settings()
    base = s.mini_app_url.rstrip("/")
    bot = (s.telegram_bot_username or "").lstrip("@")
    btc = req.amount_sats / 1e8 if req.amount_sats else None
    uri = f"bitcoin:{req.address}" + (f"?amount={btc:.8f}".rstrip("0").rstrip(".") if btc else "")
    out = {"pay_url": f"{base}/pay/{req.id}", "bitcoin_uri": uri}
    if bot:
        out["telegram_url"] = f"https://t.me/{bot}?start=pay_{req.id}"
    return out


def _pay_out(req: PaymentRequest) -> dict:
    return {**svc.request_public(req), "redirect_url": req.redirect_url, **_links(req)}


@router.post("/payment-requests", status_code=status.HTTP_201_CREATED)
async def create_payment_request(payload: PayReqIn, caller: ApiCaller, session: DbSession) -> dict:
    network = payload.network or caller.network or get_settings().onchain_network
    if caller.key and network != caller.key.network:
        raise HTTPException(422, f"This key is for {caller.key.network}.")
    sats = payload.amount_sats
    if sats is None and payload.amount is not None:
        if not payload.currency:
            raise HTTPException(422, "Give a currency with amount, e.g. NGN.")
        from app.api.v1.group_pay import to_sats

        sats = await to_sats(payload.amount, payload.currency.upper())
        if not sats:
            raise HTTPException(503, f"No live rate for {payload.currency.upper()} right now. Send amount_sats instead.")
    try:
        req = await svc.create_request(session, caller.user, network=network, amount_sats=sats, note=payload.note)
    except svc.HandleError as exc:
        raise HTTPException(422, str(exc)) from exc
    req.api_key_id = caller.key.id if caller.key else None
    req.meta = payload.metadata or None
    req.redirect_url = payload.redirect_url
    await session.commit()
    return _pay_out(req)


@router.get("/payment-requests/{request_id}")
async def get_payment_request(request_id: str, caller: ApiCaller, session: DbSession) -> dict:
    req = await session.get(PaymentRequest, request_id)
    if req is None or req.user_id != caller.user.id:
        raise HTTPException(404, "No such payment request.")
    try:
        await svc.refresh_request(session, req, get_settings())
    except Exception as exc:
        log.warning("request_check_failed", request_id=req.id, error=type(exc).__name__)
    return _pay_out(req)


@router.get("/payment-requests")
async def list_payment_requests(
    caller: ApiCaller, session: DbSession, limit: int = Query(default=20, ge=1, le=100),
    status_: str | None = Query(default=None, alias="status"),
) -> dict:
    q = select(PaymentRequest).where(PaymentRequest.user_id == caller.user.id)
    if status_:
        q = q.where(PaymentRequest.status == status_)
    rows = (await session.execute(q.order_by(PaymentRequest.created_at.desc()).limit(limit))).scalars().all()
    return {"data": [_pay_out(r) for r in rows]}


@router.post("/payment-requests/{request_id}/cancel")
async def cancel_payment_request(request_id: str, caller: ApiCaller, session: DbSession) -> dict:
    req = await session.get(PaymentRequest, request_id)
    if req is None or req.user_id != caller.user.id:
        raise HTTPException(404, "No such payment request.")
    if req.status == "open":
        req.status = "cancelled"
        await wh.queue_event(session, req.user_id, "request.cancelled", svc.request_public(req))
        await session.commit()
    return _pay_out(req)


# ------------------------------------------------------------------ webhooks


class HookIn(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    events: list[str] = Field(default_factory=lambda: ["request.paid"])


class HookOut(BaseModel):
    id: str
    url: str
    events: list[str]
    secret: str
    active: bool
    created_at: datetime


def _hook_out(h: WebhookEndpoint) -> HookOut:
    return HookOut(id=h.id, url=h.url, events=h.events or [], secret=h.secret, active=h.active, created_at=h.created_at)


@router.get("/webhooks", response_model=list[HookOut])
async def list_hooks(user: CurrentUser, session: DbSession) -> list[HookOut]:
    rows = await session.execute(select(WebhookEndpoint).where(WebhookEndpoint.user_id == user.id, WebhookEndpoint.active))
    return [_hook_out(h) for h in rows.scalars()]


@router.post("/webhooks", response_model=HookOut, status_code=status.HTTP_201_CREATED)
async def create_hook(payload: HookIn, user: CurrentUser, session: DbSession) -> HookOut:
    try:
        url = wh.check_url(payload.url)
    except wh.WebhookUrlError as exc:
        raise HTTPException(422, str(exc)) from exc
    bad = [e for e in payload.events if e not in wh.EVENTS]
    if bad:
        raise HTTPException(422, f"Unknown events: {', '.join(bad)}. Use request.paid or request.cancelled.")
    n = len((await session.execute(select(WebhookEndpoint.id).where(WebhookEndpoint.user_id == user.id, WebhookEndpoint.active))).all())
    if n >= MAX_HOOKS:
        raise HTTPException(422, f"You can have up to {MAX_HOOKS} webhooks.")
    h = WebhookEndpoint(user_id=user.id, url=url, secret=wh.new_secret(), events=payload.events or ["request.paid"])
    session.add(h)
    await session.commit()
    return _hook_out(h)


@router.delete("/webhooks/{hook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hook(hook_id: str, user: CurrentUser, session: DbSession) -> None:
    h = await session.get(WebhookEndpoint, hook_id)
    if h and h.user_id == user.id:
        h.active = False
        await session.commit()


@router.post("/webhooks/{hook_id}/test")
async def test_hook(hook_id: str, user: CurrentUser, session: DbSession) -> dict:
    h = await session.get(WebhookEndpoint, hook_id)
    if h is None or h.user_id != user.id or not h.active:
        raise HTTPException(404, "No such webhook.")
    session.add(WebhookDelivery(endpoint_id=h.id, event="ping", payload={"type": "ping", "data": {"message": "Hello from Satish"}},
                                next_attempt_at=_now()))
    await session.commit()
    result = await wh.deliver_pending(session, limit=20)
    last = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.endpoint_id == h.id).order_by(WebhookDelivery.created_at.desc()).limit(1)
    )
    return {"delivered": bool(last and last.status == "delivered"), "status_code": last.last_status_code if last else None,
            "error": last.last_error if last else None, "summary": result}


@router.get("/webhooks/{hook_id}/deliveries")
async def hook_deliveries(hook_id: str, user: CurrentUser, session: DbSession) -> list[dict]:
    h = await session.get(WebhookEndpoint, hook_id)
    if h is None or h.user_id != user.id:
        raise HTTPException(404, "No such webhook.")
    rows = (
        await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.endpoint_id == hook_id).order_by(WebhookDelivery.created_at.desc()).limit(30)
        )
    ).scalars().all()
    return [
        {"id": d.id, "event": d.event, "status": d.status, "attempts": d.attempts, "last_status_code": d.last_status_code,
         "last_error": d.last_error, "created_at": d.created_at, "delivered_at": d.delivered_at}
        for d in rows
    ]
