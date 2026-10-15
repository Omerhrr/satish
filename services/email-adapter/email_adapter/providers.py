"""Email adapter (phase 9): draft -> preview -> approval -> send.

Two providers with the SAME interface:
- ``CannedEmailProvider``  — deterministic, no network; every receipt states
  plainly that nothing was transmitted. Default dev mode.
- ``SmtpEmailProvider``    — real delivery via stdlib smtplib executed off
  the event loop. Its outcome taxonomy is honest about uncertainty:
  * definite refusal (auth rejected, recipient refused, DATA rejected)
    -> ``refused`` — safe to report "failed, safe to retry";
  * transport failure (timeout, connection dropped, unknown state)
    -> ``unknown`` — the send MIGHT have happened; the system records
    ``unknown_outcome`` and never retries silently.

This mirrors the phase-3 wallet broadcast taxonomy: uncertain outcomes are
disclosed, not guessed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from xp_core.logging import get_logger

log = get_logger(__name__)

CANNED_DISCLOSURE = (
    "canned email provider: no network transmission occurred; this receipt "
    "is a deterministic local record"
)


@dataclass(slots=True)
class SendOutcome:
    """Terminal result of one send attempt."""

    status: str  # sent | refused | unknown
    provider: str
    detail: str
    disclosure: str
    message_id: str | None = None

    @property
    def is_definite(self) -> bool:
        return self.status in {"sent", "refused"}


class EmailProvider:
    name = "base"

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        credential: dict | None = None,
    ) -> SendOutcome:  # pragma: no cover - interface
        raise NotImplementedError


class CannedEmailProvider(EmailProvider):
    """Deterministic offline provider. Never opens a socket."""

    name = "canned"

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        credential: dict | None = None,
    ) -> SendOutcome:
        message_id = f"canned-{abs(hash((to, subject, len(body)))) % 10**12:012d}"
        return SendOutcome(
            status="sent",
            provider=self.name,
            detail=f"accepted for {to} (deterministic local record)",
            disclosure=CANNED_DISCLOSURE,
            message_id=message_id,
        )


class SmtpEmailProvider(EmailProvider):
    """Real SMTP delivery (stdlib smtplib, off-loop via asyncio.to_thread).

    ``credential`` is the decrypted connection payload from the vault:
    {host, port, username, password, starttls?}.
    """

    name = "smtp"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        credential: dict | None = None,
    ) -> SendOutcome:
        import smtplib
        from email.message import EmailMessage
        from email.utils import make_msgid

        if not credential:
            return SendOutcome(
                status="refused",
                provider=self.name,
                detail="no stored credential for connection",
                disclosure="definite refusal: send was never attempted",
            )
        host = str(credential.get("host", ""))
        port = int(credential.get("port", 587))
        username = str(credential.get("username", ""))
        password = str(credential.get("password", ""))
        starttls = bool(credential.get("starttls", True))

        msg = EmailMessage()
        msg["From"] = username
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        msg_id = make_msgid(domain=host.split(":")[0] or "localhost")

        def _deliver() -> None:
            with smtplib.SMTP(host, port, timeout=self.timeout_seconds) as client:
                client.ehlo()
                if starttls:
                    client.starttls()
                    client.ehlo()
                client.login(username, password)
                client.send_message(msg)

        try:
            await asyncio.wait_for(
                asyncio.to_thread(_deliver), timeout=self.timeout_seconds + 5
            )
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused) as exc:
            return SendOutcome(
                status="refused",
                provider=self.name,
                detail=f"server refused the send: {exc.__class__.__name__}",
                disclosure="definite refusal: the message was not accepted by the server",
            )
        except smtplib.SMTPRecipientsRefused as exc:
            return SendOutcome(
                status="refused",
                provider=self.name,
                detail=f"recipient refused: {exc.recipients}",
                disclosure="definite refusal: the message was not accepted for delivery",
            )
        except smtplib.SMTPDataError as exc:
            return SendOutcome(
                status="refused",
                provider=self.name,
                detail=f"DATA rejected: {exc}",
                disclosure="definite refusal: the message content was rejected",
            )
        except (TimeoutError, OSError, smtplib.SMTPException) as exc:
            # Timeout/OSError mid-session is UNCERTAIN: the server may have
            # accepted the message before the failure. Disclose, never retry.
            log.warning("smtp_send_unknown_outcome", error=exc.__class__.__name__)
            return SendOutcome(
                status="unknown",
                provider=self.name,
                detail=(
                    f"transport failure ({exc.__class__.__name__}); the server may or "
                    "may not have accepted the message"
                ),
                disclosure=(
                    "UNKNOWN outcome: the send may have completed; the system will NOT "
                    "retry automatically — resend requires a new draft and a new approval"
                ),
            )
        return SendOutcome(
            status="sent",
            provider=self.name,
            detail=f"accepted by {host}:{port} for {to}",
            disclosure="delivered via SMTP; server accepted the message",
            message_id=msg_id,
        )


def get_email_provider(settings) -> EmailProvider:
    """Published mode switch. Unknown modes fall back to canned WITH callers
    required to disclose — silently pretending to be real is forbidden."""
    mode = (settings.email_send_mode or "canned").lower()
    if mode == "smtp":
        return SmtpEmailProvider()
    return CannedEmailProvider()
