"""Notification relay sweep (phase 9, KL-06).

Pushes condition notifications to Telegram via the Bot API. The invariant is
EXACTLY ONE relay decision per notification: every sweep pass ends each
never-relayed notification in a terminal ``relay_status`` of

- ``sent``     - provider accepted the message;
- ``refused``  - provider definitively refused (blocked bot, chat not found,
  bad token). Refusals are never retried - retrying a refusal only spams;
- ``unknown``  - the send MIGHT have completed (timeout, transport error,
  5xx). Unknown outcomes are never retried automatically; the row records
  the disclosure so nobody later mistakes silence for safety;
- ``skipped``  - the relay deliberately did not attempt: read in-app before
  the push, no linked Telegram account, or past the lookback window.

The provider is injected (canned | bot_api) so this module never imports the
adapter package - the worker wires them together, mirroring the email flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import Notification, ScheduledJob, TelegramAccount

log = get_logger(__name__)


class RelayProvider(Protocol):
    """Structural type shared with telegram_adapter providers."""

    name: str

    async def send_message(
        self, *, chat_id: int, text: str
    ) -> Any:  # RelayOutcome
        ...


@dataclass(slots=True)
class RelayCounters:
    attempted: int = 0
    sent: int = 0
    refused: int = 0
    unknown: int = 0
    skipped_read: int = 0
    skipped_no_account: int = 0
    skipped_stale: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "attempted": self.attempted,
            "sent": self.sent,
            "refused": self.refused,
            "unknown": self.unknown,
            "skipped_read": self.skipped_read,
            "skipped_no_account": self.skipped_no_account,
            "skipped_stale": self.skipped_stale,
        }


def render_notification_text(row: Notification, job_name: str | None) -> str:
    """Plain-text message body per notification kind (no parse-mode)."""
    payload = row.payload or {}
    label = f" for \"{job_name}\"" if job_name else ""
    if row.kind == "automation.run_succeeded":
        return f"Satish automation{label}: run succeeded."
    if row.kind == "automation.run_failed":
        error = payload.get("error") or "unknown error"
        return f"Satish automation{label}: run failed - {error}"
    if row.kind == "automation.auto_paused":
        reason = payload.get("reason") or "policy"
        return (
            f"Satish automation{label}: paused automatically ({reason}). "
            "Review it in the Mini App before resuming."
        )
    if row.kind == "automation.balance_below":
        balance = payload.get("balance")
        threshold = payload.get("threshold")
        return (
            f"Satish automation{label}: balance fell below threshold "
            f"({balance} TK < {threshold} TK). Fund TK credits to keep it running."
        )
    if row.kind == "request.paid":
        amount = payload.get("amount_sats") or 0
        note = payload.get("note")
        what = f" for \"{note}\"" if note else ""
        return f"Payment received: {amount:,} sats{what}. It's in your Satish wallet."
    if row.kind in ("wallet.received", "wallet.confirmed"):
        amount = int(payload.get("amount_sats") or 0)
        test = " (test coins)" if payload.get("network") == "testnet" else ""
        if row.kind == "wallet.confirmed":
            return f"✅ The {amount:,} sats{test} you received are now confirmed. They're safe in your Satish wallet."
        if payload.get("confirmed"):
            return f"📥 You received {amount:,} sats{test}. It's confirmed and in your Satish wallet."
        return f"📥 You're receiving {amount:,} sats{test}. It's waiting to confirm; we'll tell you when it does."
    if row.kind == "price.alert":
        cur = payload.get("currency", "")
        word = "above" if payload.get("direction") == "above" else "below"
        return (
            f"🔔 Bitcoin is now {payload.get('price_text', '')} ({word} your alert at "
            f"{payload.get('target_text', '')}). Open Satish to send, receive or save."
        ) if cur else "🔔 Your bitcoin price alert was hit."
    if row.kind == "savings.goal_reached":
        return f"🎉 You reached your savings goal \"{payload.get('name', '')}\". Well done!"
    return f"Satish notification ({row.kind})."


async def relay_pending_notifications(
    session: AsyncSession,
    settings: Settings,
    provider: RelayProvider,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """One sweep: one terminal relay decision per never-relayed notification."""
    now = now or datetime.now(UTC)
    lookback = timedelta(hours=settings.telegram_relay_lookback_hours)
    rows = (
        (
            await session.execute(
                select(Notification)
                .where(Notification.relayed_at.is_(None))
                .order_by(Notification.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return RelayCounters().as_dict()

    user_ids = {row.user_id for row in rows}
    accounts = (
        await session.execute(
            select(TelegramAccount).where(TelegramAccount.user_id.in_(user_ids))
        )
    ).scalars()
    chat_by_user: dict[str, int] = {
        account.user_id: account.telegram_user_id for account in accounts
    }
    job_ids = {row.job_id for row in rows if row.job_id}
    labels: dict[str, str] = {}
    if job_ids:
        jobs = (
            await session.execute(
                select(ScheduledJob).where(ScheduledJob.id.in_(job_ids))
            )
        ).scalars()
        for job in jobs:
            objective = (job.task_template or {}).get("objective")
            labels[job.id] = str(objective)[:80] if objective else job.schedule

    counters = RelayCounters()
    for row in rows:
        if row.read_at is not None:
            row.relay_status = "skipped"
            row.relay_detail = "read in-app before relay; push suppressed"
            row.relayed_at = now
            counters.skipped_read += 1
            continue
        chat_id = chat_by_user.get(row.user_id)
        if chat_id is None:
            row.relay_status = "skipped"
            row.relay_detail = "no linked telegram account; nothing to push to"
            row.relayed_at = now
            counters.skipped_no_account += 1
            continue
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
        if now - created > lookback:
            row.relay_status = "skipped"
            row.relay_detail = (
                f"past the {settings.telegram_relay_lookback_hours}h relay "
                "lookback window; push suppressed as stale"
            )
            row.relayed_at = now
            counters.skipped_stale += 1
            continue

        text = render_notification_text(row, labels.get(row.job_id or ""))
        counters.attempted += 1
        outcome = await provider.send_message(chat_id=chat_id, text=text)
        row.relay_status = outcome.status
        detail = outcome.detail
        if outcome.message_id is not None:
            detail = f"{detail} (message_id={outcome.message_id})"
        row.relay_detail = f"{detail} | {outcome.disclosure}"
        row.relayed_at = now
        if outcome.status == "sent":
            counters.sent += 1
        elif outcome.status == "refused":
            counters.refused += 1
        else:
            counters.unknown += 1

    await session.commit()
    log.info("relay_sweep_complete", **counters.as_dict(), provider=provider.name)
    return counters.as_dict()
