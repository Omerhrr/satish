"""Kaduna Kicks: a pretend online shop that takes payment with Satish.

It plays the part of a developer's own website, so developers can watch a
real integration end to end in a normal browser tab:

  GET  /api/demo-shop/                 the shop (a self-contained page)
  POST /api/demo-shop/checkout         the shop's server: prices the cart from
                                       its own catalogue and creates a Satish
                                       payment request, exactly like a merchant's
                                       backend calling POST /api/v1/dev/payment-requests
  GET  /api/demo-shop/orders/{id}      the shop's server checking if it's paid

Whose money? The shop is opened from the developer portal with a short-lived
signed pass (POST /api/v1/dev/demo-shop). Orders are paid to that developer's
own Satish wallet, so testing costs nothing. Without a valid pass the shop
still shows its products but can't take orders.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import get_settings
from xp_core.db import get_session
from xp_core.models.entities import PaymentRequest, User

router = APIRouter(prefix="/api/demo-shop", tags=["demo-shop"])
DbSession = Annotated[AsyncSession, Depends(get_session)]

PASS_TTL = 4 * 3600
PAGE = Path(__file__).with_name("demo_shop.html")

# The shop's own catalogue. Prices are decided here, never by the browser.
CATALOGUE: dict[str, dict] = {
    "runners": {"name": "Harmattan Runners", "price": 2100},
    "heels": {"name": "Owambe Heels", "price": 2600},
    "boots": {"name": "Zaria Leather Boots", "price": 3400},
    "tote": {"name": "Kano Woven Tote", "price": 1800},
    "backpack": {"name": "Campus Backpack", "price": 2300},
    "cap": {"name": "Satoshi Cap", "price": 900},
}
SHIPPING_SATS = 300


def _secret() -> bytes:
    s = get_settings()
    seed = s.connections_credential_key or s.telegram_bot_token
    if seed:
        return hashlib.sha256(b"satish-demo-shop/" + seed.encode()).digest()
    path = Path(s.artifact_dir) / ".demo_shop_secret"
    try:
        return bytes.fromhex(path.read_text().strip())
    except (OSError, ValueError):
        key = secrets.token_bytes(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key.hex())
        except OSError:
            pass
        return key


def make_pass(user_id: str, network: str, ttl: int = PASS_TTL) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"u": user_id, "n": network, "e": int(time.time()) + ttl}).encode()).decode().rstrip("=")
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{mac}"


def read_pass(token: str | None) -> dict:
    try:
        body, mac = (token or "").split(".", 1)
        want = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac, want):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if data["e"] < time.time():
            raise ValueError
        return data
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(401, "This demo shop link has expired. Open it again from Satish for developers.") from None


async def _merchant(session: AsyncSession, token: str | None) -> tuple[User, str]:
    data = read_pass(token)
    user = await session.get(User, data["u"])
    if user is None:
        raise HTTPException(401, "Open the demo shop again from Satish for developers.")
    return user, data["n"]


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def shop_page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/products")
async def products() -> dict:
    return {"shipping_sats": SHIPPING_SATS, "products": [{"id": k, **v} for k, v in CATALOGUE.items()]}


class Line(BaseModel):
    id: str
    qty: int = Field(ge=1, le=9)


class CheckoutIn(BaseModel):
    items: list[Line] = Field(min_length=1, max_length=20)
    name: str = Field(default="", max_length=60)
    city: str = Field(default="", max_length=60)


@router.post("/checkout")
async def checkout(body: CheckoutIn, session: DbSession, x_shop_pass: Annotated[str | None, Header()] = None) -> dict:
    from app.api.v1.developers import Caller, PayReqIn, create_payment_request

    user, network = await _merchant(session, x_shop_pass)
    lines, total = [], SHIPPING_SATS
    for it in body.items:
        p = CATALOGUE.get(it.id)
        if p is None:
            raise HTTPException(422, f"Unknown product {it.id}.")
        lines.append(f"{it.qty}x {p['name']}")
        total += p["price"] * it.qty
    order_id = "KK-" + secrets.token_hex(3).upper()
    # Exactly what a merchant's backend sends to POST /api/v1/dev/payment-requests.
    sent = {
        "amount_sats": total,
        "note": f"Kaduna Kicks {order_id}",
        "metadata": {"order_id": order_id, "items": [i.model_dump() for i in body.items], "ship_to": body.city[:60]},
        "network": network,
    }
    out = await create_payment_request(PayReqIn(**sent), Caller(user, None), session)
    return {
        "order_id": order_id,
        "lines": lines,
        "shipping_sats": SHIPPING_SATS,
        "request_sent": sent,
        "payment": out,
    }


@router.get("/orders/{request_id}")
async def order_status(request_id: str, session: DbSession, x_shop_pass: Annotated[str | None, Header()] = None) -> dict:
    from app.api.v1.developers import Caller, get_payment_request

    user, _ = await _merchant(session, x_shop_pass)
    req = await session.get(PaymentRequest, request_id)
    if req is None or req.user_id != user.id:
        raise HTTPException(404, "No such order.")
    return await get_payment_request(request_id, Caller(user, None), session)

