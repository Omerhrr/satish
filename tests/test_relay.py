"""Phase-9 KL-06 tests: Telegram notification relay.

Acceptance coverage:
- "Telegram relay for notifications (bot token configured path)" ->
  provider taxonomy tests + sweep one-decision invariant tests
- Honest outcome taxonomy: sent | refused | unknown, unknown never retried
- Skip policy: read in-app, no linked account, past lookback window
- API discloses relay_status per notification
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from telegram_adapter import (
    CannedTelegramRelayProvider,
    build_relay_provider,
)
from telegram_adapter.providers import (
    REFUSED_DISCLOSURE,
    UNKNOWN_DISCLOSURE,
    BotApiTelegramRelayProvider,
)
from xp_core.config import Settings
from xp_core.models.entities import Notification, TelegramAccount
from xp_core.services.relay import relay_pending_notifications

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


def bot_api_handler(status_code: int = 200, body: dict | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/bot")
        assert request.url.path.endswith("/sendMessage")
        payload = request.read()
        assert b"chat_id" in payload
        return httpx.Response(
            status_code,
            json=body if body is not None else {"ok": True, "result": {"message_id": 42}},
        )

    return handler


def failing_handler(exc: Exception):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


# provider taxonomy


@pytest.mark.asyncio
async def test_canned_provider_records_without_transmission():
    provider = CannedTelegramRelayProvider()
    outcome = await provider.send_message(chat_id=123, text="hello")
    assert outcome.status == "sent"
    assert outcome.provider == "canned"
    assert "no message was transmitted" in outcome.disclosure
    assert outcome.message_id is not None


@pytest.mark.asyncio
async def test_bot_api_ok_is_sent():
    provider = BotApiTelegramRelayProvider(
        bot_token="T", transport=httpx.MockTransport(bot_api_handler(200))
    )
    outcome = await provider.send_message(chat_id=1, text="hi")
    assert outcome.status == "sent"
    assert outcome.message_id == 42


@pytest.mark.asyncio
async def test_bot_api_4xx_is_refused_and_names_reason():
    provider = BotApiTelegramRelayProvider(
        bot_token="T",
        transport=httpx.MockTransport(
            bot_api_handler(400, {"ok": False, "description": "chat not found"})
        ),
    )
    outcome = await provider.send_message(chat_id=1, text="hi")
    assert outcome.status == "refused"
    assert "chat not found" in outcome.detail
    assert outcome.disclosure == REFUSED_DISCLOSURE


@pytest.mark.asyncio
async def test_bot_api_401_bad_token_is_refused():
    provider = BotApiTelegramRelayProvider(
        bot_token="T",
        transport=httpx.MockTransport(
            bot_api_handler(401, {"ok": False, "description": "Unauthorized"})
        ),
    )
    outcome = await provider.send_message(chat_id=1, text="hi")
    assert outcome.status == "refused"
    assert "Unauthorized" in outcome.detail


@pytest.mark.asyncio
async def test_bot_api_5xx_is_unknown():
    provider = BotApiTelegramRelayProvider(
        bot_token="T",
        transport=httpx.MockTransport(bot_api_handler(502, {"ok": False})),
    )
    outcome = await provider.send_message(chat_id=1, text="hi")
    assert outcome.status == "unknown"
    assert outcome.disclosure == UNKNOWN_DISCLOSURE


@pytest.mark.asyncio
async def test_bot_api_timeout_is_unknown():
    provider = BotApiTelegramRelayProvider(
        bot_token="T",
        transport=httpx.MockTransport(
            failing_handler(httpx.ReadTimeout("timed out"))
        ),
    )
    outcome = await provider.send_message(chat_id=1, text="hi")
    assert outcome.status == "unknown"
    assert "will NOT retry" in outcome.disclosure


@pytest.mark.asyncio
async def test_bot_api_ok_false_on_200_is_unknown():
    provider = BotApiTelegramRelayProvider(
        bot_token="T",
        transport=httpx.MockTransport(
            bot_api_handler(200, {"ok": False, "description": "weird"})
        ),
    )
    outcome = await provider.send_message(chat_id=1, text="hi")
    assert outcome.status == "unknown"


def test_bot_api_provider_refuses_to_construct_without_token():
    with pytest.raises(ValueError, match="requires a bot token"):
        BotApiTelegramRelayProvider(bot_token="")


def test_factory_canned_is_default():
    provider = build_relay_provider(Settings())
    assert provider.name == "canned"


def test_factory_bot_api_without_token_raises():
    with pytest.raises(ValueError, match="requires XP_TELEGRAM_BOT_TOKEN"):
        build_relay_provider(Settings(telegram_relay_mode="bot_api"))


def test_factory_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown telegram relay mode"):
        build_relay_provider(Settings(telegram_relay_mode="carrier_pigeon"))


# sweep behavior


@pytest.fixture()
def sweep_settings(settings):
    return settings


async def make_notification(session, user_id, *, kind="automation.run_succeeded",
                            read=False, age=None, payload=None):
    row = Notification(
        user_id=user_id,
        kind=kind,
        payload=payload or {},
        created_at=(NOW - (age or timedelta(minutes=1))).replace(tzinfo=None),
    )
    if read:
        row.read_at = (NOW - timedelta(seconds=30)).replace(tzinfo=None)
    session.add(row)
    await session.flush()
    return row


class RecordingProvider:
    name = "recording"

    def __init__(self, status="sent"):
        self.status = status
        self.calls: list[dict] = []

    async def send_message(self, *, chat_id: int, text: str):
        self.calls.append({"chat_id": chat_id, "text": text})
        return type(
            "O",
            (),
            {
                "status": self.status,
                "detail": f"recorded ({self.status})",
                "disclosure": "test disclosure",
                "message_id": 7 if self.status == "sent" else None,
            },
        )()


@pytest.mark.asyncio
async def test_sweep_sends_unread_recent_and_is_terminal(session, dev_user, sweep_settings):
    await make_notification(session, dev_user.id)
    provider = RecordingProvider()
    counters = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert counters["sent"] == 1
    assert counters["attempted"] == 1
    row = (await session.execute(select(Notification))).scalar_one()
    assert row.relay_status == "sent"
    assert row.relayed_at is not None
    assert "message_id=7" in row.relay_detail
    account = (
        await session.execute(
            select(TelegramAccount).where(TelegramAccount.user_id == dev_user.id)
        )
    ).scalar_one()
    assert provider.calls[0]["chat_id"] == account.telegram_user_id

    second = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert second["attempted"] == 0
    assert len(provider.calls) == 1  # one decision, never re-sent


@pytest.mark.asyncio
async def test_sweep_skips_read_notifications(session, dev_user, sweep_settings):
    await make_notification(session, dev_user.id, read=True)
    provider = RecordingProvider()
    counters = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert counters["skipped_read"] == 1
    assert provider.calls == []
    row = (await session.execute(select(Notification))).scalar_one()
    assert row.relay_status == "skipped"
    assert "read in-app" in row.relay_detail


@pytest.mark.asyncio
async def test_sweep_skips_users_without_telegram_account(session, sweep_settings):
    from xp_core.models.entities import User

    bare = User(display_name="no telegram")
    session.add(bare)
    await session.flush()
    await make_notification(session, bare.id)
    provider = RecordingProvider()
    counters = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert counters["skipped_no_account"] == 1
    assert provider.calls == []


@pytest.mark.asyncio
async def test_sweep_skips_stale_beyond_lookback(session, dev_user, sweep_settings):
    await make_notification(session, dev_user.id, age=timedelta(hours=25))
    provider = RecordingProvider()
    counters = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert counters["skipped_stale"] == 1
    assert provider.calls == []
    row = (await session.execute(select(Notification))).scalar_one()
    assert "lookback" in row.relay_detail


@pytest.mark.asyncio
async def test_unknown_outcome_is_recorded_never_retried(session, dev_user, sweep_settings):
    await make_notification(session, dev_user.id)
    provider = RecordingProvider(status="unknown")
    counters = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert counters["unknown"] == 1
    row = (await session.execute(select(Notification))).scalar_one()
    assert row.relay_status == "unknown"
    assert "test disclosure" in row.relay_detail

    second = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert second["attempted"] == 0
    assert len(provider.calls) == 1  # no silent retries


@pytest.mark.asyncio
async def test_refused_outcome_is_terminal(session, dev_user, sweep_settings):
    await make_notification(session, dev_user.id)
    provider = RecordingProvider(status="refused")
    counters = await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert counters["refused"] == 1
    row = (await session.execute(select(Notification))).scalar_one()
    assert row.relay_status == "refused"


@pytest.mark.asyncio
async def test_rendered_text_carries_objective_and_error(session, dev_user, sweep_settings):
    job_row = Notification(
        user_id=dev_user.id,
        kind="automation.run_failed",
        payload={"error": "budget exhausted"},
        created_at=(NOW - timedelta(minutes=1)).replace(tzinfo=None),
    )
    session.add(job_row)
    await session.flush()
    provider = RecordingProvider()
    await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    assert "budget exhausted" in provider.calls[0]["text"]


# API disclosure + worker wiring


@pytest.mark.asyncio
async def test_api_discloses_relay_status(session, dev_user, sweep_settings):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    await make_notification(session, dev_user.id)
    provider = RecordingProvider()
    await relay_pending_notifications(session, sweep_settings, provider, now=NOW)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = (await client.get("/api/v1/notifications")).json()
    assert listed["notifications"][0]["relay_status"] == "sent"


@pytest.mark.asyncio
async def test_worker_relay_job_runs_end_to_end(session, dev_user, monkeypatch):
    import worker.jobs.relay as relay_job

    counters = await relay_job.relay_notifications_job({})
    assert counters["provider"] == "canned"
    assert counters["sent"] == 0  # no notifications yet


@pytest.mark.asyncio
async def test_relay_message_skips_without_settings_change(session, dev_user):
    """Default lookback (24h) keeps a 25h-old unread notification unpushed."""
    await make_notification(session, dev_user.id, age=timedelta(hours=25))
    provider = RecordingProvider()
    counters = await relay_pending_notifications(
        session, Settings(), provider, now=NOW
    )
    assert counters["skipped_stale"] == 1
