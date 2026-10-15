"""Email adapter (phase 9): honest draft-preview-approval-send flow."""

from email_adapter.providers import (
    CANNED_DISCLOSURE,
    CannedEmailProvider,
    EmailProvider,
    SendOutcome,
    SmtpEmailProvider,
    get_email_provider,
)

__all__ = [
    "CANNED_DISCLOSURE",
    "CannedEmailProvider",
    "EmailProvider",
    "SendOutcome",
    "SmtpEmailProvider",
    "get_email_provider",
]
