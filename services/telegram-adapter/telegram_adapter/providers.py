"""Telegram relay providers (phase 9, KL-06): notification -> chat push.

Two providers with the SAME interface:
- ``CannedTelegramRelayProvider``  - deterministic, no network; every receipt
  states plainly that nothing was transmitted. Default dev mode.
- ``BotApiTelegramRelayProvider``  - real delivery via the Telegram Bot API
  ``sendMessage`` endpoint. Its outcome taxonomy is honest about
  uncertainty:
  * HTTP 200 with ``ok: true``            -> ``sent`` (Telegram accepted)
  * 4xx with an error description         -> ``refused`` (definite: blocked
    bot, chat not found, bad token) - safe to report "failed, do not retry"
    because retrying a refusal only spams;
  * timeouts, connection errors, 5xx      -> ``unknown`` - the message
    MIGHT have arrived; the system records ``unknown_outcome`` and never
    retries silently.

This mirrors the phase-9 email taxonomy and the phase-3 wallet broadcast
rule: uncertain outcomes are disclosed, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from xp_core.config import Settings
from xp_core.logging import get_logger

log = get_logger(__name__)

CANNED_DISCLOSURE = (
    "canned telegram relay: no message was transmitted over the network; "
    "this receipt is a deterministic local record"
)
UNKNOWN_DISCLOSURE = (
    "UNKNOWN outcome: the send may have completed; the relay will NOT retry "
    "automatically"
)
REFUSED_DISCLOSURE = (
    "delivery refused by Telegram; the relay does not retry refusals"
)

BOT_API_BASE = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10.0


@dataclass(slots=True)
class RelayOutcome:
    """Terminal result of one relay attempt."""

    status: str  # sent | refused | unknown
    provider: str
    detail: str
    disclosure: str
    message_id: int | None = None

    @property
    def is_definite(self) -> bool:
        return self.status in {"sent", "refused"}


class TelegramRelayProvider:
    name = "base"

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
    ) -> RelayOutcome:  # pragma: no cover - interface
        raise NotImplementedError


class CannedTelegramRelayProvider(TelegramRelayProvider):
    """Deterministic offline provider. Never opens a socket."""

    name = "canned"

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
    ) -> RelayOutcome:
        message_id = abs(hash((chat_id, text))) % 10**10
        return RelayOutcome(
            status="sent",
            provider=self.name,
            detail=f"accepted for chat {chat_id} (deterministic local record)",
            disclosure=CANNED_DISCLOSURE,
            message_id=message_id,
        )


class BotApiTelegramRelayProvider(TelegramRelayProvider):
    """Real delivery via the Telegram Bot API sendMessage endpoint."""

    name = "bot_api"

    def __init__(
        self,
        bot_token: str,
        base_url: str = BOT_API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not bot_token:
            raise ValueError(
                "BotApiTelegramRelayProvider requires a bot token; refusing "
                "to construct a provider that would fabricate delivery"
            )
        self._bot_token = bot_token
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
    ) -> RelayOutcome:
        url = f"{self._base_url}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try:
            async with httpx.AsyncClient(
                timeout=SEND_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException:
            log.warning("telegram_relay_unknown_outcome", reason="timeout")
            return RelayOutcome(
                status="unknown",
                provider=self.name,
                detail="request timed out; delivery state unknown",
                disclosure=UNKNOWN_DISCLOSURE,
            )
        except httpx.HTTPError as exc:
            log.warning(
                "telegram_relay_unknown_outcome", reason=exc.__class__.__name__
            )
            return RelayOutcome(
                status="unknown",
                provider=self.name,
                detail=f"transport error ({exc.__class__.__name__}); delivery state unknown",
                disclosure=UNKNOWN_DISCLOSURE,
            )
        if resp.status_code == httpx.codes.OK:
            body = resp.json()
            if body.get("ok") is True:
                return RelayOutcome(
                    status="sent",
                    provider=self.name,
                    detail="telegram accepted the message",
                    disclosure="delivered via Telegram Bot API",
                    message_id=body.get("result", {}).get("message_id"),
                )
            return RelayOutcome(
                status="unknown",
                provider=self.name,
                detail="HTTP 200 but Telegram reported ok=false",
                disclosure=UNKNOWN_DISCLOSURE,
            )
        if 400 <= resp.status_code < 500:
            description = "telegram rejected the request"
            try:
                body = resp.json()
                description = body.get("description", description)
            except ValueError:
                pass
            log.info("telegram_relay_refused", http_status=resp.status_code)
            return RelayOutcome(
                status="refused",
                provider=self.name,
                detail=f"HTTP {resp.status_code}: {description}",
                disclosure=REFUSED_DISCLOSURE,
            )
        return RelayOutcome(
            status="unknown",
            provider=self.name,
            detail=f"HTTP {resp.status_code} from Bot API; delivery state unknown",
            disclosure=UNKNOWN_DISCLOSURE,
        )


def build_relay_provider(settings: Settings) -> TelegramRelayProvider:
    """Factory: XP_TELEGRAM_RELAY_MODE selects canned | bot_api.

    bot_api mode without a configured token raises at construction - the
    system never silently downgrades a requested real send to canned.
    """
    mode = settings.telegram_relay_mode
    if mode == "canned":
        return CannedTelegramRelayProvider()
    if mode == "bot_api":
        if not settings.telegram_bot_token:
            raise ValueError(
                "XP_TELEGRAM_RELAY_MODE=bot_api requires XP_TELEGRAM_BOT_TOKEN"
            )
        return BotApiTelegramRelayProvider(bot_token=settings.telegram_bot_token)
    raise ValueError(f"unknown telegram relay mode: {mode!r}")
