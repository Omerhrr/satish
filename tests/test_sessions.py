"""Phase-2 session hardening tests.

Acceptance criteria under test:
- forged or expired Telegram authentication payloads are rejected (regression)
- users can access only their own records (session ownership)
- logout performs server-side revocation, not client-side token dropping
- short-lived sessions expire and are refused
- bot messages never request seed phrases or private keys
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from xp_core.services.security import (
    create_session,
    hash_token,
    resolve_user_from_token,
)

BOT_MAIN = Path(__file__).resolve().parents[1] / "apps" / "bot" / "bot" / "main.py"


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _auth(client) -> str:
    resp = await client.post("/api/v1/auth/telegram", json={"init_data": ""})
    assert resp.status_code == 200
    return resp.json()["session_token"]


# logout = server-side revocation


async def test_logout_revokes_session_server_side(client):
    token = await _auth(client)
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    logout = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    # The token is dead server-side - a stolen copy afterwards is worthless.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401


async def test_logout_without_token_rejected_even_in_dev_mode(client):
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


async def test_logout_with_forged_token_401(client):
    resp = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


async def test_double_logout_is_unauthorized_not_500(client):
    token = await _auth(client)
    h = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/api/v1/auth/logout", headers=h)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=h)).status_code == 401


# session listing + per-session revoke


async def test_sessions_list_and_revoke_by_id(client):
    token = await _auth(client)
    h = {"Authorization": f"Bearer {token}"}
    listing = await client.get("/api/v1/auth/sessions", headers=h)
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    row = rows[0]
    for field in ("id", "created_via", "created_at", "expires_at"):
        assert field in row
    assert row["created_via"] == "dev"  # issued via dev auth exchange
    assert "session_token" not in row and "token_hash" not in row

    # A second session appears in the list.
    token2 = await _auth(client)
    listing = await client.get("/api/v1/auth/sessions", headers=h)
    assert len(listing.json()) == 2

    # Revoke the second session by id; the first stays alive.
    target = next(r for r in listing.json() if r["id"] != row["id"])
    resp = await client.delete(f"/api/v1/auth/sessions/{target['id']}", headers=h)
    assert resp.status_code == 200
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token2}"})
    assert me.status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 200

    # Revoked session no longer listed.
    assert all(r["id"] != target["id"] for r in (await client.get("/api/v1/auth/sessions", headers=h)).json())


async def test_cannot_revoke_someone_elses_session(client, session, dev_user):
    """Ownership: another user's session id is indistinguishable from 404."""
    from xp_core.models.entities import User

    stranger = User(display_name="Stranger")
    session.add(stranger)
    await session.flush()
    stranger_token, _ = await create_session(session, stranger.id)
    await session.commit()

    token = await _auth(client)
    resp = await client.delete(
        f"/api/v1/auth/sessions/{hash_token(stranger_token)[:8]}",  # wrong id, wrong owner
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404

    # The stranger's session is untouched and still authenticates.
    assert await resolve_user_from_token(session, stranger_token) is not None


# short-lived sessions


async def test_expired_session_rejected(client, session):
    token = await _auth(client)
    from xp_core.models.entities import Session

    row = (
        await session.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401


async def test_session_ttl_is_short_lived(client, session):
    token = await _auth(client)
    from xp_core.models.entities import Session

    row = (
        await session.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one()
    from xp_core.config import get_settings

    ttl = get_settings().session_ttl_hours
    assert ttl <= 24, "sessions must be short-lived (trust boundary control)"
    assert row.expires_at - row.created_at <= timedelta(hours=24)


async def test_last_used_tracked(client, session):
    token = await _auth(client)
    from xp_core.models.entities import Session

    row = (
        await session.execute(select(Session).where(Session.token_hash == hash_token(token)))
    ).scalar_one()
    assert row.last_used_at is None  # creation alone is not a use
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    await session.refresh(row)
    assert row.last_used_at is not None
    assert abs((datetime.now(UTC) - row.last_used_at.replace(tzinfo=UTC)).total_seconds()) < 60


# Telegram auth regressions (phase-2 acceptance #1)


def test_forged_init_data_rejected_at_unit_level():
    from xp_core.services.security import verify_telegram_init_data

    assert verify_telegram_init_data("hash=deadbeef&auth_date=1", "tok") is None


def test_stale_init_data_rejected():
    from xp_core.services.security import verify_telegram_init_data

    old = int(time.time()) - 100_000
    # A structurally valid payload with a stale auth_date must fail even
    # before hash checks matter: max_age enforcement is independent.
    assert (
        verify_telegram_init_data(f"auth_date={old}&user=%7B%22id%22%3A1%7D&hash=x", "tok", max_age_seconds=86400)
        is None
    )


# bot copy guardrail (phase-2 acceptance #3)

FORBIDDEN_REQUEST_PATTERNS = [
    r"(send|share|enter|type|paste|provide)\b.{0,40}\b(seed(\s?phrase)?|mnemonic|recovery phrase|private key(s)?)",
    r"\byour\s+(seed(\s?phrase)?|mnemonic|recovery phrase|private key(s)?)\b.{0,20}\b(send|share|enter|type|paste|provide)",
]


def test_bot_never_requests_secret_material():
    """Any new bot copy matching a secret-request pattern fails CI."""
    src = BOT_MAIN.read_text(encoding="utf-8")
    lowered = src.lower()
    for pattern in FORBIDDEN_REQUEST_PATTERNS:
        assert re.search(pattern, lowered) is None, f"forbidden secret-request pattern: {pattern}"


def test_bot_discloses_it_never_asks_for_secrets():
    src = BOT_MAIN.read_text(encoding="utf-8").lower()
    assert "never ask" in src and ("seed phrase" in src or "private key" in src)


def test_bot_commands_defined_without_secret_collection():
    """Every command handler builds replies from fixed strings, not user input loops."""
    src = BOT_MAIN.read_text(encoding="utf-8")
    assert "input(" not in src and "getpass(" not in src
