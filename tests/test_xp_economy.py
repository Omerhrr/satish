"""Phase-5 XP economy tests: pricing, purchases/receipts, reconciliation,
budget cap enforcement, concurrency, refund audit.

Acceptance coverage:
- "One settled payment credits XP at most once" -> test_settle_credits_once_*
  (structural: CAS + ledger idempotency, replayed) and the reconciliation
  1:1 intent<->entry checks.
- "Concurrent reservations cannot overdraw XP" -> test_concurrent_reservations_*
- "Failed or expired invoices do not credit XP" -> test_expired_invoice_*
- "Refunds create auditable ledger entries" -> test_refund_*
- "Balances reconcile to ledger entries" -> test_reconcile_*
- "A task cannot exceed its approved XP budget without additional
  authorization" -> test_settle_refuses_over_budget + test_increase_budget_*
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from app.services import task_service, xp_service
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from xp_core.config import get_settings
from xp_core.models.entities import AuditEvent, PaymentIntent, XpAccount, XpLedgerEntry
from xp_core.services import ledger

# -- fixtures ----------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@pytest.fixture()
async def client(session, dev_user):
    """ASGI client with a clock-controlled canned provider injected."""
    from app.main import app
    from lightning_adapter import CannedLightningProvider
    from wallet_adapter import Network

    clock = FakeClock()

    async def _client():
        return clock

    from app.services import lightning_service as svc

    svc._provider = CannedLightningProvider(Network.REGTEST, clock=clock)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.clock = clock  # type: ignore[attr-defined]
        yield c
    svc.reset_provider()


def _preimage_for(client, payment_hash: str) -> str:
    """White-box seam: the canned invoice holds the preimage a real node
    would supply server-side through the settle stream."""
    from app.services import lightning_service as svc

    provider = svc.get_provider(get_settings())
    return provider._invoices[payment_hash].invoice.preimage


# -- published pricing ---------------------------------------------------------------


async def test_rate_is_published_and_changeable(client):
    resp = await client.get("/api/v1/xp/rate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["xp_per_sat"] == get_settings().xp_per_sat
    assert body["can_change"] is True
    assert "not Bitcoin" in body["note"]


async def test_packs_list_the_published_table(client):
    resp = await client.get("/api/v1/xp/packs")
    assert resp.status_code == 200
    packs = resp.json()
    assert [p["amount_sats"] for p in packs] == [1000, 5000, 20000]
    for p in packs:
        assert p["xp_amount"] == p["amount_sats"] * get_settings().xp_per_sat
    assert len({p["pack_id"] for p in packs}) == len(packs)


# -- purchase flow ---------------------------------------------------------------------


async def test_purchase_pack_creates_invoice_with_xp_preview(client):
    resp = await client.post("/api/v1/xp/purchases", json={"pack_id": "pack_1000sats"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["amount_sats"] == 1000
    assert body["xp_amount"] == 1000 * get_settings().xp_per_sat
    assert body["bolt11"]
    assert body["ledger_entry_id"] is None  # nothing credited yet


async def test_purchase_custom_amount_and_rejections(client):
    ok = await client.post("/api/v1/xp/purchases", json={"amount_sats": 250})
    assert ok.status_code == 201
    assert ok.json()["xp_amount"] == 25_000

    unknown = await client.post("/api/v1/xp/purchases", json={"pack_id": "nope"})
    assert unknown.status_code == 404

    empty = await client.post("/api/v1/xp/purchases", json={})
    assert empty.status_code == 422


async def test_settle_credits_once_and_receipt_binds_ledger(client):
    """The full billing_flow: intent -> invoice -> settle -> credit -> receipt."""
    created = await client.post("/api/v1/xp/purchases", json={"pack_id": "pack_1000sats"})
    purchase = created.json()
    payment_hash = purchase["payment_hash"]

    settled = await client.post(
        f"/api/v1/lightning/invoices/{payment_hash}/settle",
        json={"preimage": _preimage_for(client, payment_hash)},
    )
    assert settled.status_code == 200
    assert settled.json()["credited"] is True

    # Replay: structurally incapable of double-crediting.
    replay = await client.post(
        f"/api/v1/lightning/invoices/{payment_hash}/settle",
        json={"preimage": _preimage_for(client, payment_hash)},
    )
    assert replay.status_code == 200
    assert replay.json()["credited"] is False

    # Receipt view binds the ONE ledger entry.
    view = await client.get(f"/api/v1/xp/purchases/{purchase['id']}")
    assert view.status_code == 200
    receipt = view.json()
    assert receipt["status"] == "settled"
    assert receipt["ledger_entry_id"]
    assert receipt["balance_after"] == purchase["xp_amount"]


async def test_two_distinct_settlements_credit_twice(client):
    """Each verified settled payment credits once — different intents both pay."""
    total = 0
    for _ in range(2):
        created = await client.post("/api/v1/xp/purchases", json={"amount_sats": 100})
        p = created.json()
        resp = await client.post(
            f"/api/v1/lightning/invoices/{p['payment_hash']}/settle",
            json={"preimage": _preimage_for(client, p["payment_hash"])},
        )
        assert resp.json()["credited"] is True
        total += p["xp_amount"]
    balance = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance == total


async def test_settled_purchase_has_exactly_one_ledger_entry(session, dev_user, client):
    created = await client.post("/api/v1/xp/purchases", json={"amount_sats": 500})
    purchase = created.json()
    resp = await client.post(
        f"/api/v1/lightning/invoices/{purchase['payment_hash']}/settle",
        json={"preimage": _preimage_for(client, purchase["payment_hash"])},
    )
    assert resp.status_code == 200

    count = (
        await session.execute(
            select(func.count())
            .select_from(XpLedgerEntry)
            .where(
                XpLedgerEntry.entry_type == "purchase",
                XpLedgerEntry.reference_id == purchase["id"],
            )
        )
    ).scalar_one()
    assert count == 1


async def test_expired_invoice_never_credits(session, dev_user, client):
    """Failed or expired invoices do not credit XP (acceptance #3)."""
    created = await client.post("/api/v1/xp/purchases", json={"amount_sats": 800})
    purchase = created.json()
    client.clock.advance(3601)  # age the invoice past expiry

    resp = await client.post(
        f"/api/v1/lightning/invoices/{purchase['payment_hash']}/settle",
        json={"preimage": _preimage_for(client, purchase["payment_hash"])},
    )
    assert resp.status_code == 410  # expired before settlement

    purchases = (await client.get("/api/v1/xp/purchases")).json()
    assert purchases[0]["status"] == "expired"

    entries = (
        await session.execute(select(func.count()).select_from(XpLedgerEntry))
    ).scalar_one()
    assert entries == 0  # nothing was ever credited


async def test_purchase_receipt_pdf_rendered(session, dev_user, client, tmp_path, monkeypatch):
    """Receipt artifact renders from DB rows via the inline worker bridge."""

    monkeypatch.setenv("XP_ARTIFACT_DIR", str(tmp_path))
    created = await client.post("/api/v1/xp/purchases", json={"pack_id": "pack_1000sats"})
    purchase = created.json()
    await client.post(
        f"/api/v1/lightning/invoices/{purchase['payment_hash']}/settle",
        json={"preimage": _preimage_for(client, purchase["payment_hash"])},
    )

    resp = await client.post(f"/api/v1/xp/purchases/{purchase['id']}/receipt.pdf")
    assert resp.status_code == 202
    artifact_id = resp.json()["artifact_id"]

    download = await client.get(f"/api/v1/artifacts/{artifact_id}/download")
    assert download.status_code == 200
    assert download.content[:4] == b"%PDF"


async def test_receipt_pdf_refused_for_unsettled_purchase(client):
    created = await client.post("/api/v1/xp/purchases", json={"amount_sats": 300})
    resp = await client.post(f"/api/v1/xp/purchases/{created.json()['id']}/receipt.pdf")
    assert resp.status_code == 409


# -- reconciliation ---------------------------------------------------------------------


async def test_reconcile_healthy_ledger_is_ok(session, dev_user, client):
    await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 1000})
    resp = await client.post("/api/v1/xp/reconcile")
    assert resp.status_code == 200
    report = resp.json()
    assert report["ok"] is True
    assert report["discrepancies"] == []
    assert report["checked_users"] >= 1


async def test_reconcile_flags_balance_corruption(session, dev_user, client):
    await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 1000})
    # Simulate corruption: bump the account balance without a ledger entry.
    acct = (
        await session.execute(select(XpAccount).where(XpAccount.user_id == dev_user.id))
    ).scalar_one()
    acct.balance += 500
    await session.commit()

    report = (await client.post("/api/v1/xp/reconcile")).json()
    assert report["ok"] is False
    kinds = {d["kind"] for d in report["discrepancies"]}
    assert "balance_mismatch" in kinds
    # Every flag is audited.
    flags = (
        await session.execute(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == "xp.reconciliation_flag"
            )
        )
    ).scalar_one()
    assert flags >= 1


async def test_reconcile_flags_settled_intent_without_entry(session, dev_user, client):
    """A settled receive intent MUST have exactly one purchase entry."""
    session.add(
        PaymentIntent(
            user_id=dev_user.id,
            provider_reference="deadbeef" * 8,
            amount_sats=100,
            xp_amount=10_000,
            status="settled",
            direction="receive",
            idempotency_key="receive:deadbeef",
            settled_at=datetime.now(UTC),
        )
    )
    await session.commit()

    report = (await client.post("/api/v1/xp/reconcile")).json()
    kinds = {d["kind"] for d in report["discrepancies"]}
    assert "settled_intent_without_purchase_entry" in kinds


async def test_reconcile_flags_double_credited_intent(session, dev_user, client):
    """If an intent somehow got two purchase entries, reconciliation screams."""
    session.add(
        PaymentIntent(
            id="intent-x",
            user_id=dev_user.id,
            provider_reference="cafebabe" * 8,
            amount_sats=1,
            xp_amount=100,
            status="settled",
            direction="receive",
            idempotency_key="receive:cafebabe",
        )
    )
    await ledger.credit_purchase(
        session, user_id=dev_user.id, amount=100, payment_intent_id="intent-x"
    )
    # Corrupt: second entry, same reference, different idempotency key.
    session.add(
        XpLedgerEntry(
            user_id=dev_user.id,
            entry_type="purchase",
            amount=100,
            balance_after=200,
            reference_type="payment_intent",
            reference_id="intent-x",
            idempotency_key="purchase:dup-key",
        )
    )
    await session.commit()

    report = (await client.post("/api/v1/xp/reconcile")).json()
    kinds = {d["kind"] for d in report["discrepancies"]}
    assert "purchase_credited_more_than_once" in kinds


# -- concurrency: reservations cannot overdraw ---------------------------------------------


async def test_concurrent_reservations_cannot_overdraw(session, dev_user, tmp_path):
    """8 concurrent 100-XP reservations against a 500 balance: exactly 5 win.

    Uses per-attempt sessions on a shared file-backed SQLite DB so the CAS
    UPDATE ... WHERE balance + delta >= 0 is the arbiter, exactly like two
    racing API workers against Postgres.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from xp_core.db import Base
    from xp_core.models.entities import User

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/conc.db", connect_args={"timeout": 15}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as seed:
        user = User(id="concurrent-user", status="active")
        seed.add(user)
        await seed.flush()
        await ledger.credit_purchase(
            seed, user_id=user.id, amount=500, payment_intent_id="seed-1"
        )
        await seed.commit()

    async def attempt(i: int) -> bool:
        async with factory() as s:
            try:
                await ledger.reserve_budget(
                    s, user_id=user.id, task_id=f"task-{i}", amount=100
                )
                await s.commit()
                return True
            except ledger.InsufficientBalance:
                await s.rollback()
                return False

    try:
        results = await asyncio.gather(*(attempt(i) for i in range(8)))
        assert sum(results) == 5, results
        async with factory() as check:
            acct = (
                await check.execute(
                    select(XpAccount).where(XpAccount.user_id == user.id)
                )
            ).scalar_one()
            assert acct.balance == 0
            total = (
                await check.execute(
                    select(func.coalesce(func.sum(XpLedgerEntry.amount), 0)).where(
                        XpLedgerEntry.user_id == user.id
                    )
                )
            ).scalar_one()
            assert int(total) == acct.balance  # invariant #7 holds under concurrency
    finally:
        await engine.dispose()


# -- refunds and audit -------------------------------------------------------------------


async def test_refund_is_auditable(session, dev_user):
    await ledger.credit_purchase(
        session, user_id=dev_user.id, amount=300, payment_intent_id="seed-2"
    )
    await ledger.refund(
        session, user_id=dev_user.id, amount=100, reason="failed task refund"
    )
    refund_entries = (
        await session.execute(
            select(XpLedgerEntry)
            .where(XpLedgerEntry.entry_type == "refund", XpLedgerEntry.user_id == dev_user.id)
        )
    ).scalars().all()
    assert len(refund_entries) == 1
    assert refund_entries[0].note == "failed task refund"
    assert refund_entries[0].amount == 100


async def test_refund_replay_is_idempotent(session, dev_user):
    key = "refund:test-key"
    r1 = await ledger.refund(
        session, user_id=dev_user.id, amount=50, idempotency_key=key, reason="r"
    )
    r2 = await ledger.refund(
        session, user_id=dev_user.id, amount=50, idempotency_key=key, reason="r"
    )
    assert r2.idempotent_replay is True
    assert r1.balance_after == r2.balance_after


# -- task budget cap (acceptance #6) --------------------------------------------------------


async def test_settle_refuses_over_budget(session, dev_user, client):
    grant = await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 1000})
    assert grant.status_code == 200
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Cap enforcement probe", "budget_xp": 100}
        )
    ).json()

    over = await client.post(f"/api/v1/tasks/{task['id']}/settle", json={"actual_xp": 150})
    assert over.status_code == 409
    assert "exceeds the approved budget" in over.json()["detail"]

    # Nothing extra was charged; the reservation is still held.
    balance = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance == 900


async def test_increase_budget_is_user_authorization_and_then_settle_succeeds(
    session, dev_user, client
):
    await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 1000})
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Increase then settle", "budget_xp": 100}
        )
    ).json()

    increased = await client.post(
        f"/api/v1/tasks/{task['id']}/increase-budget", json={"additional_xp": 50}
    )
    assert increased.status_code == 200
    body = increased.json()
    assert body["budget_xp"] == 150
    assert body["reserved_xp"] == 150

    # Balance dropped by the additional reservation.
    balance = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance == 850

    # Audit trail for the authorization.
    audits = (
        await session.execute(
            select(AuditEvent).where(AuditEvent.event_type == "task.budget_increased")
        )
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].metadata_redacted["new_budget_xp"] == 150

    settled = await client.post(f"/api/v1/tasks/{task['id']}/settle", json={"actual_xp": 120})
    assert settled.status_code == 200
    assert settled.json()["status"] == "completed"
    assert settled.json()["actual_xp"] == 120
    assert settled.json()["reserved_xp"] == 0

    # Ledger math: 1000 - reserve 150 + release 150 - charge 120 = 880.
    balance = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance == 880


async def test_increase_budget_rejects_completed_task(session, dev_user, client):
    await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 500})
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Already done", "budget_xp": 50}
        )
    ).json()
    await client.post(f"/api/v1/tasks/{task['id']}/settle", json={"actual_xp": 20})
    resp = await client.post(
        f"/api/v1/tasks/{task['id']}/increase-budget", json={"additional_xp": 10}
    )
    assert resp.status_code == 409


async def test_estimate_endpoint_is_deterministic(client):
    objective = "Research lightning liquidity options for a routing node"
    r1 = (
        await client.post(
            "/api/v1/tasks/estimate", json={"objective": objective, "budget_xp": 1}
        )
    ).json()
    r2 = (
        await client.post(
            "/api/v1/tasks/estimate", json={"objective": objective, "budget_xp": 1}
        )
    ).json()
    assert r1 == r2
    assert r1["estimated_xp_low"] <= r1["estimated_xp_high"]
    assert any("web.search" in a for a in r1["variable_cost_activities"])


# -- failed-task rule ------------------------------------------------------------------------


async def test_fail_task_releases_full_reservation(session, dev_user, client):
    await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 400})
    task = (
        await client.post(
            "/api/v1/tasks", json={"objective": "Will fail halfway", "budget_xp": 120}
        )
    ).json()

    failed = await task_service.fail_task(
        session, user_id=dev_user.id, task_id=task["id"], reason="worker crashed"
    )
    assert failed.status == "failed"
    assert failed.reserved_xp == 0

    balance = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance == 400  # full release, nothing charged

    audits = (
        await session.execute(select(AuditEvent).where(AuditEvent.event_type == "task.failed"))
    ).scalars().all()
    assert len(audits) == 1
    assert audits[0].metadata_redacted["released_xp"] == 120


# -- ownership ---------------------------------------------------------------------------------


async def test_purchases_are_own_records_only(session, dev_user, client):
    created = await client.post("/api/v1/xp/purchases", json={"amount_sats": 200})
    purchase_id = created.json()["id"]

    class ForeignUser:
        id = "00000000-0000-0000-0000-00000000000f"

    with pytest.raises(HTTPException) as excinfo:
        await xp_service.get_owned_purchase(session, ForeignUser(), purchase_id)
    assert excinfo.value.status_code == 404
