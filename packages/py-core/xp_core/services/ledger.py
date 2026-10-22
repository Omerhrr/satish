"""TK ledger engine enforcing the plan's ledger_invariants.

Design:
- Every mutation happens in the caller's database transaction (invariant #1).
- Balance changes use an atomic compare-and-swap UPDATE so concurrent tasks
  can never spend the same credits (invariants #4, #5) - portable across
  SQLite (dev) and Postgres (prod).
- Every balance change appends an append-only ledger entry; refunds and
  corrections are new entries (invariant #6) and balance == sum(entries)
  (invariant #7).
- Idempotency keys make every credit/replay safe (invariants #2, #3 are
  payment-side and enforced by the payments flow + unique constraints).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from xp_core.logging import get_logger
from xp_core.models.entities import AuditEvent, XpAccount, XpLedgerEntry

log = get_logger(__name__)

ENTRY_TYPES = {
    "purchase",
    "reservation",
    "reservation_release",
    "charge",
    "refund",
    "adjustment",
}


class LedgerError(Exception):
    """Base ledger error."""


class InsufficientBalance(LedgerError):
    pass


class UnknownEntryType(LedgerError):
    pass


@dataclass(slots=True)
class LedgerResult:
    entry_id: str
    entry_type: str
    amount: int
    balance_after: int
    idempotent_replay: bool = False


async def get_or_create_account(session: AsyncSession, user_id: str) -> XpAccount:
    acct = (
        await session.execute(select(XpAccount).where(XpAccount.user_id == user_id))
    ).scalar_one_or_none()
    if acct is None:
        acct = XpAccount(user_id=user_id, balance=0)
        session.add(acct)
        await session.flush()
    return acct


async def _append_entry(
    session: AsyncSession,
    *,
    user_id: str,
    entry_type: str,
    amount: int,
    reference_type: str | None,
    reference_id: str | None,
    idempotency_key: str,
    note: str | None = None,
) -> tuple[XpLedgerEntry, bool]:
    """Insert a ledger entry unless its idempotency key already exists.

    Returns (entry, idempotent_replay).
    """
    if entry_type not in ENTRY_TYPES:
        raise UnknownEntryType(entry_type)
    existing = (
        await session.execute(
            select(XpLedgerEntry).where(XpLedgerEntry.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True

    acct = await get_or_create_account(session, user_id)
    entry = XpLedgerEntry(
        user_id=user_id,
        entry_type=entry_type,
        amount=amount,
        balance_after=acct.balance,  # patched by _apply_balance_delta
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        idempotency_key=idempotency_key,
    )
    session.add(entry)
    await session.flush()
    return entry, False


async def _apply_balance_delta(
    session: AsyncSession,
    *,
    user_id: str,
    delta: int,
    entry: XpLedgerEntry,
) -> int:
    """Atomic CAS balance update; raises InsufficientBalance if it would go negative."""
    acct = await get_or_create_account(session, user_id)
    if delta < 0:
        result = await session.execute(
            update(XpAccount)
            .where(XpAccount.id == acct.id, XpAccount.balance + delta >= 0)
            .values(balance=XpAccount.balance + delta, updated_at=datetime.now(UTC))
        )
        if result.rowcount == 0:
            raise InsufficientBalance(
                f"user {user_id} balance {acct.balance} cannot cover delta {delta}"
            )
    else:
        await session.execute(
            update(XpAccount)
            .where(XpAccount.id == acct.id)
            .values(balance=XpAccount.balance + delta, updated_at=datetime.now(UTC))
        )
    await session.refresh(acct)
    entry.balance_after = acct.balance
    await session.flush()
    return acct.balance


def _new_key(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4()}"


async def credit_purchase(
    session: AsyncSession,
    *,
    user_id: str,
    amount: int,
    payment_intent_id: str,
    idempotency_key: str | None = None,
) -> LedgerResult:
    """Credit TK for exactly one verified settled payment (invariants #2, #3)."""
    if amount <= 0:
        raise LedgerError("purchase amount must be positive")
    key = idempotency_key or f"purchase:{payment_intent_id}"
    entry, replay = await _append_entry(
        session,
        user_id=user_id,
        entry_type="purchase",
        amount=amount,
        reference_type="payment_intent",
        reference_id=payment_intent_id,
        idempotency_key=key,
        note="TK purchase credited from settled payment",
    )
    if not replay:
        await _apply_balance_delta(session, user_id=user_id, delta=amount, entry=entry)
    log.info(
        "xp_purchase_credited",
        user_id=user_id,
        amount=amount,
        payment_intent_id=payment_intent_id,
        balance_after=entry.balance_after,
        idempotent_replay=replay,
    )
    return LedgerResult(entry.id, entry.entry_type, entry.amount, entry.balance_after, replay)


async def reserve_budget(
    session: AsyncSession,
    *,
    user_id: str,
    task_id: str,
    amount: int,
    idempotency_key: str | None = None,
) -> LedgerResult:
    """Atomically hold budget for a task; concurrent tasks cannot double-spend."""
    if amount <= 0:
        raise LedgerError("reservation amount must be positive")
    key = idempotency_key or f"reserve:{task_id}"
    entry, replay = await _append_entry(
        session,
        user_id=user_id,
        entry_type="reservation",
        amount=-amount,
        reference_type="task",
        reference_id=task_id,
        idempotency_key=key,
        note="Task budget reservation",
    )
    if not replay:
        await _apply_balance_delta(session, user_id=user_id, delta=-amount, entry=entry)
    log.info(
        "xp_reserved",
        user_id=user_id,
        task_id=task_id,
        amount=amount,
        balance_after=entry.balance_after,
        idempotent_replay=replay,
    )
    return LedgerResult(entry.id, entry.entry_type, entry.amount, entry.balance_after, replay)


async def release_reservation(
    session: AsyncSession,
    *,
    user_id: str,
    task_id: str,
    amount: int,
    idempotency_key: str | None = None,
) -> LedgerResult:
    """Return unused reserved TK to the available balance."""
    if amount <= 0:
        raise LedgerError("release amount must be positive")
    key = idempotency_key or f"release:{task_id}"
    entry, replay = await _append_entry(
        session,
        user_id=user_id,
        entry_type="reservation_release",
        amount=amount,
        reference_type="task",
        reference_id=task_id,
        idempotency_key=key,
        note="Unused reservation released",
    )
    if not replay:
        await _apply_balance_delta(session, user_id=user_id, delta=amount, entry=entry)
    log.info(
        "xp_released",
        user_id=user_id,
        task_id=task_id,
        amount=amount,
        balance_after=entry.balance_after,
        idempotent_replay=replay,
    )
    return LedgerResult(entry.id, entry.entry_type, entry.amount, entry.balance_after, replay)


async def charge_usage(
    session: AsyncSession,
    *,
    user_id: str,
    task_id: str,
    amount: int,
    idempotency_key: str | None = None,
) -> LedgerResult:
    """Charge actual metered usage (task_charge_flow #6). Positive amount."""
    if amount <= 0:
        raise LedgerError("charge amount must be positive")
    key = idempotency_key or f"charge:{task_id}"
    entry, replay = await _append_entry(
        session,
        user_id=user_id,
        entry_type="charge",
        amount=-amount,
        reference_type="task",
        reference_id=task_id,
        idempotency_key=key,
        note="Metered usage charge within approved cap",
    )
    if not replay:
        await _apply_balance_delta(session, user_id=user_id, delta=-amount, entry=entry)
    log.info(
        "xp_charged",
        user_id=user_id,
        task_id=task_id,
        amount=amount,
        balance_after=entry.balance_after,
        idempotent_replay=replay,
    )
    return LedgerResult(entry.id, entry.entry_type, entry.amount, entry.balance_after, replay)


async def settle_task(
    session: AsyncSession,
    *,
    user_id: str,
    task_id: str,
    reserved_xp: int,
    actual_xp: int,
    idempotency_key: str | None = None,
) -> tuple[LedgerResult, LedgerResult]:
    """Canonical task settlement: release the full hold, then charge actual usage.

    Net effect is exactly -actual_xp (within the approved cap), while the
    ledger keeps an explicit audit trail of hold -> release -> charge.
    """
    if actual_xp > reserved_xp:
        raise LedgerError("actual usage cannot exceed the approved reservation cap")
    release_res, charge_res = None, None
    if reserved_xp > 0:
        release_res = await release_reservation(
            session,
            user_id=user_id,
            task_id=task_id,
            amount=reserved_xp,
            idempotency_key=f"{idempotency_key or f'settle:{task_id}'}:release",
        )
    if actual_xp > 0:
        charge_res = await charge_usage(
            session,
            user_id=user_id,
            task_id=task_id,
            amount=actual_xp,
            idempotency_key=f"{idempotency_key or f'settle:{task_id}'}:charge",
        )
    return release_res, charge_res  # type: ignore[return-value]


async def refund(
    session: AsyncSession,
    *,
    user_id: str,
    amount: int,
    task_id: str | None = None,
    reason: str = "",
    idempotency_key: str | None = None,
) -> LedgerResult:
    """Refunds append new entries rather than rewriting history (invariant #6)."""
    if amount <= 0:
        raise LedgerError("refund amount must be positive")
    key = idempotency_key or _new_key(f"refund:{task_id or user_id}")
    entry, replay = await _append_entry(
        session,
        user_id=user_id,
        entry_type="refund",
        amount=amount,
        reference_type="task" if task_id else None,
        reference_id=task_id,
        idempotency_key=key,
        note=reason or "Refund",
    )
    if not replay:
        await _apply_balance_delta(session, user_id=user_id, delta=amount, entry=entry)
    return LedgerResult(entry.id, entry.entry_type, entry.amount, entry.balance_after, replay)


async def adjust(
    session: AsyncSession,
    *,
    user_id: str,
    amount: int,  # signed
    reason: str,
    idempotency_key: str | None = None,
) -> LedgerResult:
    """Administrative adjustment with reason + audit record (ledger_entities #8)."""
    if amount == 0:
        raise LedgerError("adjustment amount must be non-zero")
    key = idempotency_key or _new_key("adjustment")
    entry, replay = await _append_entry(
        session,
        user_id=user_id,
        entry_type="adjustment",
        amount=amount,
        reference_type="admin",
        reference_id=None,
        idempotency_key=key,
        note=reason,
    )
    if not replay:
        await _apply_balance_delta(session, user_id=user_id, delta=amount, entry=entry)
        session.add(
            AuditEvent(
                actor_type="admin",
                event_type="xp.adjustment",
                resource_type="xp_account",
                resource_id=user_id,
                metadata_redacted={"reason": reason, "amount": amount},
            )
        )
        await session.flush()
    return LedgerResult(entry.id, entry.entry_type, entry.amount, entry.balance_after, replay)


async def reconcile(session: AsyncSession, user_id: str) -> tuple[int, int]:
    """Verify balance == sum(entries) for a user; returns (balance, sum_of_entries)."""
    acct = await get_or_create_account(session, user_id)
    row = (
        await session.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM xp_ledger_entries WHERE user_id = :u"),
            {"u": user_id},
        )
    ).scalar_one()
    return acct.balance, int(row)
