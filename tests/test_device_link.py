"""Browser extension sign-in by bot code."""

from __future__ import annotations

from xp_core.config import get_settings

from app.api.v1.device_link import bot_key
from tests.test_agent_runtime import client  # noqa: F401  (fixture)


async def test_extension_links_to_telegram_account_once(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "7000:TEST")
    start = (await client.post("/api/v1/auth/link/start")).json()
    code, poll = start["code"], start["poll_token"]
    assert len(code) == 9 and code[4] == "-"
    assert (await client.post("/api/v1/auth/link/poll", json={"poll_token": poll})).status_code == 202

    body = {"code": code.lower().replace("-", " "), "telegram_user_id": 424242, "username": "ada"}
    assert (await client.post("/api/v1/auth/link/confirm", json=body)).status_code == 403  # bot only
    ok = await client.post("/api/v1/auth/link/confirm", json=body, headers={"X-Bot-Key": bot_key("7000:TEST")})
    assert ok.json() == {"status": "linked"}

    got = await client.post("/api/v1/auth/link/poll", json={"poll_token": poll})
    assert got.status_code == 200
    token = got.json()["session_token"]
    bal = await client.get("/api/v1/xp/balance", headers={"Authorization": f"Bearer {token}"})
    assert bal.json()["balance_xp"] == s.tk_welcome_bonus  # same account economy as Telegram
    again = await client.post("/api/v1/auth/link/poll", json={"poll_token": poll})
    assert again.status_code == 404  # a session is handed out once


async def test_wrong_code_and_extension_cors(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "7000:TEST")
    bad = await client.post(
        "/api/v1/auth/link/confirm",
        json={"code": "ZZZZ-ZZZZ", "telegram_user_id": 1},
        headers={"X-Bot-Key": bot_key("7000:TEST")},
    )
    assert bad.json() == {"status": "not_found"}
    pre = await client.options(
        "/api/v1/xp/rate",
        headers={"Origin": "chrome-extension://abcdefghijklmnop", "Access-Control-Request-Method": "GET"},
    )
    assert pre.headers.get("access-control-allow-origin") in ("chrome-extension://abcdefghijklmnop", "*")
