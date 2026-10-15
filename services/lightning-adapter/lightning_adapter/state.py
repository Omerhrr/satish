"""Canonical Lightning state machines (phase 4, decision D11).

Both providers — the canned semantics provider and the real lnd gRPC
adapter — MUST route every lifecycle mutation through these transitions so
that offline tests and the live node enforce identical rules.

Invoice (receive):  pending -> settled | expired
  lnd reports elapsed invoices as CANCELED; our API surfaces them as
  ``expired``. Settling an expired invoice is refused.

Payment (send):     prepared -> authorized -> in_flight -> succeeded | failed
  ``prepare`` is a fee preview + authorization digest (nothing moves);
  ``authorize`` binds the digest the user reviewed; ``submit`` is the node
  submission and its outcome is terminal. Uncertain node outages map to
  PaymentUncertain — never silently retried.
"""

from __future__ import annotations

INVOICE_STATES = ("pending", "settled", "expired")

INVOICE_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"settled", "expired"},
    "settled": set(),
    "expired": set(),
}

PAYMENT_STATES = ("created", "prepared", "authorized", "in_flight", "succeeded", "failed")

PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    "created": {"prepared"},
    "prepared": {"authorized", "failed"},
    "authorized": {"in_flight", "failed"},
    "in_flight": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
}


class InvalidTransition(Exception):
    """Raised when a lifecycle mutation violates the canonical machine."""


class InvoiceExpired(Exception):
    """Raised when an action requires a live invoice but it has elapsed."""


def next_invoice_state(current: str, target: str) -> str:
    """Validate and return the target invoice state."""
    if current not in INVOICE_TRANSITIONS:
        raise InvalidTransition(f"unknown invoice state {current!r}")
    if target not in INVOICE_TRANSITIONS[current]:
        raise InvalidTransition(f"invoice cannot move {current!r} -> {target!r}")
    return target


def next_payment_state(current: str, target: str) -> str:
    """Validate and return the target payment state."""
    if current not in PAYMENT_TRANSITIONS:
        raise InvalidTransition(f"unknown payment state {current!r}")
    if target not in PAYMENT_TRANSITIONS[current]:
        raise InvalidTransition(f"payment cannot move {current!r} -> {target!r}")
    return target


def invoice_is_live(current: str) -> bool:
    """A live invoice can still be settled."""
    return current == "pending"
