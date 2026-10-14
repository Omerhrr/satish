"""XP ledger invariant tests (plan: xp_economy.ledger_invariants)."""

from __future__ import annotations

import pytest
from xp_core.services import ledger
from xp_core.services.ledger import InsufficientBalance, LedgerError


async def test_purchase_increases_balance(session, dev_user):
    await ledger.credit_purchase(
        session, user_id=dev_user.id, amount=500, payment_intent_id="pi_1"
    )
    balance, total = await ledger.reconcile(session, dev_user.id)
    assert balance == total == 500


async def test_balance_equals_sum_of_entries(session, dev_user):
    """Invariant #7: balance must reconcile with sum of ledger entries."""
    await ledger.credit_purchase(session, user_id=dev_user.id, amount=1000, payment_intent_id="pi_1")
    await ledger.reserve_budget(session, user_id=dev_user.id, task_id="t1", amount=300)
    await ledger.settle_task(
        session, user_id=dev_user.id, task_id="t1", reserved_xp=300, actual_xp=80
    )
    balance, total = await ledger.reconcile(session, dev_user.id)
    assert balance == total
    assert balance == 1000 - 80  # net charge only


async def test_payment_credited_once(session, dev_user):
    """Invariant #3: a payment event can be credited only once."""
    first = await ledger.credit_purchase(
        session, user_id=dev_user.id, amount=250, payment_intent_id="pi_same"
    )
    replay = await ledger.credit_purchase(
        session, user_id=dev_user.id, amount=250, payment_intent_id="pi_same"
    )
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    balance, _ = await ledger.reconcile(session, dev_user.id)
    assert balance == 250


async def test_concurrent_tasks_cannot_overdraw(session, dev_user):
    """Invariants #4/#5: a task cannot reserve more than available; concurrent
    reservations cannot spend the same credits (CAS update)."""
    await ledger.credit_purchase(session, user_id=dev_user.id, amount=100, payment_intent_id="pi_1")
    await ledger.reserve_budget(session, user_id=dev_user.id, task_id="t1", amount=80)
    with pytest.raises(InsufficientBalance):
        await ledger.reserve_budget(session, user_id=dev_user.id, task_id="t2", amount=30)
    balance, _ = await ledger.reconcile(session, dev_user.id)
    assert balance == 20


async def test_settlement_cannot_exceed_reserved_cap(session, dev_user):
    """task_charge_flow #6: charge actual cost within the approved cap."""
    await ledger.credit_purchase(session, user_id=dev_user.id, amount=1000, payment_intent_id="pi_1")
    await ledger.reserve_budget(session, user_id=dev_user.id, task_id="t1", amount=100)
    with pytest.raises(LedgerError):
        await ledger.settle_task(
            session, user_id=dev_user.id, task_id="t1", reserved_xp=100, actual_xp=101
        )


async def test_refund_appends_new_entry(session, dev_user):
    """Invariant #6: refunds create new entries rather than rewriting history."""
    await ledger.credit_purchase(session, user_id=dev_user.id, amount=500, payment_intent_id="pi_1")
    await ledger.refund(session, user_id=dev_user.id, amount=100, reason="failed task")
    entries = (await ledger.reconcile(session, dev_user.id))[0]
    assert entries == 600
    # original purchase entry is untouched — two entries now exist
    from sqlalchemy import func, select
    from xp_core.models.entities import XpLedgerEntry

    count = (
        await session.execute(
            select(func.count()).select_from(XpLedgerEntry).where(XpLedgerEntry.user_id == dev_user.id)
        )
    ).scalar_one()
    assert count == 2


async def test_adjustment_records_audit_event(session, dev_user):
    from sqlalchemy import select
    from xp_core.models.entities import AuditEvent

    await ledger.adjust(session, user_id=dev_user.id, amount=42, reason="goodwill credit")
    event = (
        await session.execute(select(AuditEvent).where(AuditEvent.event_type == "xp.adjustment"))
    ).scalar_one()
    assert event.metadata_redacted == {"reason": "goodwill credit", "amount": 42}
