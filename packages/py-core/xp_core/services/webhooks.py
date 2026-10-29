"""Developer webhooks: Satish POSTs events to a developer's HTTPS endpoint.

Each request carries:
  Satish-Event: request.paid
  Satish-Delivery: <delivery id>          (same id on every retry: dedupe on it)
  Satish-Signature: t=<unix>,v1=<hex>     HMAC-SHA256(secret, f"{t}.{body}")

Verify by recomputing the HMAC over "<t>.<raw body>" with your endpoint
secret and rejecting timestamps older than 5 minutes. Deliveries retry with
backoff (30 s, 2 min, 10 min, 1 h, 6 h) until a 2xx, then are marked failed.
Endpoints must be https on a public address (no private or local IPs).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.logging import get_logger
from xp_core.models.entities import WebhookDelivery, WebhookEndpoint

log = get_logger(__name__)

EVENTS = {"request.paid", "request.cancelled", "ping"}
BACKOFF = [30, 120, 600, 3600, 21600]


class WebhookUrlError(ValueError):
    pass


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def check_url(url: str, *, resolve: bool = True) -> str:
    """https only, no credentials, public host only."""
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not u.hostname:
        raise WebhookUrlError("Use an https:// address.")
    if u.username or u.password:
        raise WebhookUrlError("Don't put a username or password in the address.")
    if u.port not in (None, 443, 8443):
        raise WebhookUrlError("Use port 443 (or 8443).")
    host = u.hostname
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise WebhookUrlError("Webhooks must go to a public address.")
    if resolve:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise WebhookUrlError("That address can't be found.") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise WebhookUrlError("Webhooks must go to a public address.")
    return url.strip()


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    t = int(ts or time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    """Reference check (what a developer's server does)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - t) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))


async def queue_event(session: AsyncSession, user_id: str, event: str, data: dict[str, Any]) -> int:
    """Create a delivery for each of the user's active endpoints that wants it."""
    rows = (
        await session.execute(select(WebhookEndpoint).where(WebhookEndpoint.user_id == user_id, WebhookEndpoint.active))
    ).scalars().all()
    n = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    for ep in rows:
        if ep.events and event not in ep.events and event != "ping":
            continue
        session.add(
            WebhookDelivery(
                endpoint_id=ep.id,
                event=event,
                payload={"type": event, "created": int(time.time()), "data": data},
                next_attempt_at=now,
            )
        )
        n += 1
    return n


async def deliver_pending(
    session: AsyncSession, *, transport: httpx.AsyncBaseTransport | None = None, limit: int = 50, resolve: bool = True
) -> dict[str, int]:
    now = datetime.now(UTC).replace(tzinfo=None)
    due = (
        await session.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
    ).scalars().all()
    sent = failed = 0
    async with httpx.AsyncClient(timeout=10, transport=transport, follow_redirects=False) as client:
        for d in due:
            ep = await session.get(WebhookEndpoint, d.endpoint_id)
            if ep is None or not ep.active:
                d.status = "failed"
                d.last_error = "endpoint removed"
                continue
            body = json.dumps({"id": d.id, **d.payload}, separators=(",", ":")).encode()
            d.attempts += 1
            try:
                check_url(ep.url, resolve=resolve)
                r = await client.post(
                    ep.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Satish-Webhooks/1",
                        "Satish-Event": d.event,
                        "Satish-Delivery": d.id,
                        "Satish-Signature": sign(ep.secret, body),
                    },
                )
                d.last_status_code = r.status_code
                ok = 200 <= r.status_code < 300
                d.last_error = None if ok else f"HTTP {r.status_code}"
            except (httpx.HTTPError, WebhookUrlError) as exc:
                ok = False
                d.last_error = str(exc)[:300] or type(exc).__name__
            if ok:
                d.status = "delivered"
                d.delivered_at = now
                sent += 1
            elif d.attempts > len(BACKOFF):
                d.status = "failed"
                failed += 1
            else:
                d.next_attempt_at = now + timedelta(seconds=BACKOFF[d.attempts - 1])
    await session.commit()
    return {"due": len(due), "delivered": sent, "failed": failed}
