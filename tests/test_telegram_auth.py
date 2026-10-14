"""Telegram initData validation tests — forged/stale payloads are rejected."""

from __future__ import annotations

import hashlib
import hmac
import time

from xp_core.services.security import verify_telegram_init_data

BOT_TOKEN = "7000000000:TESTTOKEN-for-unit-tests-only"


def _sign(pairs: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()


def make_init_data(user: str = '{"id": 111, "username": "satoshi"}', age_seconds: int = 0) -> str:
    pairs = {
        "user": user,
        "auth_date": str(int(time.time()) - age_seconds),
        "query_id": "AAF9tE0aAAAAAHXylnjAjw",
    }
    pairs["hash"] = _sign(pairs)
    return "&".join(f"{k}={v}" for k, v in pairs.items())


def test_valid_init_data_accepted():
    identity = verify_telegram_init_data(make_init_data(), BOT_TOKEN, now=int(time.time()))
    assert identity is not None
    assert identity.telegram_user_id == 111
    assert identity.username == "satoshi"


def test_forged_hash_rejected():
    data = make_init_data().replace("satoshi", "attacker")  # tamper after signing
    assert verify_telegram_init_data(data, BOT_TOKEN) is None


def test_wrong_bot_token_rejected():
    assert verify_telegram_init_data(make_init_data(), "123:wrongtoken") is None


def test_stale_payload_rejected():
    stale = make_init_data(age_seconds=3 * 86400)
    assert verify_telegram_init_data(stale, BOT_TOKEN, max_age_seconds=86400) is None


def test_missing_hash_rejected():
    data = make_init_data()
    no_hash = "&".join(p for p in data.split("&") if not p.startswith("hash="))
    assert verify_telegram_init_data(no_hash, BOT_TOKEN) is None


def test_garbage_rejected():
    assert verify_telegram_init_data("not-a-valid-payload", BOT_TOKEN) is None
    assert verify_telegram_init_data("", BOT_TOKEN) is None
