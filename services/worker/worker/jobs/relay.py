"""Notification relay job (phase 9, KL-06).

Worker cron heartbeat that pushes unread condition notifications to
Telegram through the telegram-adapter provider (canned | bot_api). Every
notification gets exactly ONE relay decision; unknown outcomes are never
retried automatically (see xp_core.services.relay).
"""

from __future__ import annotations

from typing import Any

from xp_core.config import get_settings
from xp_core.logging import get_logger, setup_logging

log = get_logger(__name__)


async def relay_notifications_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq job: one relay sweep over never-relayed notifications."""
    setup_logging(get_settings().log_level)
    from telegram_adapter import build_relay_provider
    from xp_core.db import get_session_factory
    from xp_core.services.relay import relay_pending_notifications

    settings = get_settings()
    provider = build_relay_provider(settings)
    factory = get_session_factory()
    async with factory() as session:
        counters = await relay_pending_notifications(session, settings, provider)
    return {"provider": provider.name, **counters}
