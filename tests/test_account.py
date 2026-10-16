"""KL-10 tests: self-serve account export + ledger-aware closure.

Acceptance coverage:
- "Data export": one JSON document with every owned surface; secrets
  (token hashes, credential ciphertexts) never exported and their absence
  disclosed.
- "Ledger-aware closure": refuses with precise reasons while anything is
  in flight (running tasks, pending approvals, open payment intents,
  nonzero balance - no fabricated forfeit entry), requires clean
  reconciliation, then erases user content, anonymizes identity, scrubs
  content of structural rows, and keeps the immutable money/evidence trail.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import (
    Approval,
    Artifact,
    AuditEvent,
    ConnectedService,
    EmailDraft,
    Notification,
    PaymentIntent,
    ScheduledJob,
    ServiceCredential,
    Session,
    Task,
    TaskEvent,
    TaskStep,
    TelegramAccount,
    Wallet,
    WalletTransaction,
    XpLedgerEntry,
)
from xp_core.services import ledger
from xp_core.services.closure import ERASED_ON_CLOSURE
from xp_core.services.security import create_session
from xp_core.services.storage import LocalStorage

# fixtures


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
def settings():
    return get_settings()


async def seed_rich_user(session, user, *, with_balance: bool = False) -> None:
    """A realistic owned-data set for export/closure tests."""
    if with_balance:
        await ledger.credit_purchase(
            session, user_id=user.id, amount=40, payment_intent_id=f"seed-{user.id}"
        )
    wallet = Wallet(
        user_id=user.id, wallet_type="software", network="regtest", status="active"
    )
    session.add(wallet)
    await session.flush()
    session.add(
        WalletTransaction(
            wallet_id=wallet.id,
            transaction_type="receive",
            amount_sats=1000,
            fee_sats=0,
            status="confirmed",
        )
    )
    task = Task(
        user_id=user.id,
        objective="find suppliers",
        status="completed",
        budget_xp=10,
        deliverable="report.pdf",
    )
    session.add(task)
    await session.flush()
    session.add(
        TaskStep(task_id=task.id, step_index=0, tool_name="web.search", status="succeeded")
    )
    session.add(TaskEvent(task_id=task.id, seq=0, event_type="plan", payload={"steps": 1}))
    session.add(
        ScheduledJob(
            user_id=user.id,
            task_template={"objective": "weekly monitor"},
            schedule="hourly",
            status="active",
        )
    )
    session.add(
        Notification(user_id=user.id, kind="automation.run_succeeded", payload={})
    )
    session.add(
        EmailDraft(
            user_id=user.id,
            to_address="a@b.c",
            subject="s",
            body="b",
            digest="d" * 64,
            status="drafted",
        )
    )
    connection = ConnectedService(user_id=user.id, provider="smtp", status="linked")
    session.add(connection)
    await session.flush()
    session.add(
        ServiceCredential(
            connection_id=connection.id, ciphertext="fernet-blob-never-exported"
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_export_contains_all_sections_and_no_secrets(
    client, session, dev_user, settings
):
    await seed_rich_user(session, dev_user)
    await session.commit()
    resp = await client.get("/api/v1/account/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    doc = resp.json()
    sections = doc["sections"]
    for name in (
        "profile",
        "telegram_accounts",
        "sessions",
        "wallets",
        "wallet_transactions",
        "payment_intents",
        "xp_account",
        "xp_ledger_entries",
        "tasks",
        "task_steps",
        "task_events",
        "approvals",
        "artifacts",
        "scheduled_jobs",
        "automation_runs",
        "notifications",
        "connected_services",
        "email_drafts",
    ):
        assert name in sections, f"missing export section: {name}"
    assert sections["tasks"][0]["objective"] == "find suppliers"
    assert sections["connected_services"][0]["provider"] == "smtp"
    # secrets never exported
    assert all("token_hash" not in s for s in sections["sessions"])
    assert "service_credentials" not in sections
    assert "fernet-blob" not in resp.text
    assert any("token hash" in d.lower() for d in doc["disclosures"])
    assert any("credential" in d.lower() for d in doc["disclosures"])


@pytest.mark.asyncio
async def test_closure_blocked_by_running_task(client, session, dev_user):
    session.add(
        Task(
            user_id=dev_user.id,
            objective="running now",
            status="running",
            budget_xp=5,
        )
    )
    await session.commit()
    resp = await client.post(
        "/api/v1/account/closure", json={"confirm": "CLOSE"}
    )
    assert resp.status_code == 409
    assert any("running" in r for r in resp.json()["detail"]["reasons"])


@pytest.mark.asyncio
async def test_closure_blocked_by_pending_approval(client, session, dev_user):
    session.add(
        Approval(
            user_id=dev_user.id,
            action_type="email.send",
            action_digest="a" * 64,
            status="pending",
        )
    )
    await session.commit()
    resp = await client.post("/api/v1/account/closure", json={"confirm": "CLOSE"})
    assert resp.status_code == 409
    assert any("approval" in r for r in resp.json()["detail"]["reasons"])


@pytest.mark.asyncio
async def test_closure_blocked_by_open_payment_intent(client, session, dev_user):
    session.add(
        PaymentIntent(
            user_id=dev_user.id,
            amount_sats=1000,
            xp_amount=100_000,
            status="pending",
            direction="receive",
            idempotency_key=f"pi-{uuid.uuid4()}",
        )
    )
    await session.commit()
    resp = await client.post("/api/v1/account/closure", json={"confirm": "CLOSE"})
    assert resp.status_code == 409
    assert any("payment intent" in r for r in resp.json()["detail"]["reasons"])


@pytest.mark.asyncio
async def test_closure_blocked_by_nonzero_balance_discloses_no_forfeit(
    client, session, dev_user
):
    from tests.test_automation import seed_xp

    await seed_xp(session, dev_user, 40)
    resp = await client.post("/api/v1/account/closure", json={"confirm": "CLOSE"})
    assert resp.status_code == 409
    reasons = resp.json()["detail"]["reasons"]
    assert any("balance" in r for r in reasons)
    assert any("forfeit" in r for r in reasons)  # honesty: no fabricated write


@pytest.mark.asyncio
async def test_closure_blocked_by_dirty_reconciliation(client, session, dev_user):
    from tests.test_automation import seed_xp

    await seed_xp(session, dev_user, 40)
    await ledger.charge_usage(
        session, user_id=dev_user.id, task_id="t-dirty", amount=40
    )
    await session.commit()
    # Inject a ledger entry behind the balance cache: balance check passes
    # (0) but reconciliation must refuse (sum of entries != balance).
    import uuid as _uuid

    session.add(
        XpLedgerEntry(
            user_id=dev_user.id,
            entry_type="purchase",
            amount=25,
            balance_after=25,
            idempotency_key=f"dirty-{_uuid.uuid4()}",
        )
    )
    await session.commit()
    resp = await client.post("/api/v1/account/closure", json={"confirm": "CLOSE"})
    assert resp.status_code == 409
    assert any("reconciliation" in r for r in resp.json()["detail"]["reasons"])


@pytest.mark.asyncio
async def test_closure_requires_typed_confirmation(client, session, dev_user):
    resp = await client.post("/api/v1/account/closure", json={"confirm": "close"})
    assert resp.status_code == 422  # Literal["CLOSE"] gate


@pytest.mark.asyncio
async def test_closure_happy_path_erases_anonymizes_retains(
    client, session, dev_user, settings
):
    await seed_rich_user(session, dev_user)
    # a real artifact file on disk
    storage = LocalStorage(settings.artifact_dir)
    key = f"closure-test/{uuid.uuid4()}.pdf"
    storage.save_bytes(key, b"%PDF-1.4 test")
    session.add(
        Artifact(
            user_id=dev_user.id,
            object_key=key,
            content_type="application/pdf",
            size_bytes=12,
            status="ready",
        )
    )
    ledger_count_before = len(
        (await session.execute(select(XpLedgerEntry))).scalars().all()
    )
    await session.commit()

    resp = await client.post("/api/v1/account/closure", json={"confirm": "CLOSE"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "closed"
    erased = body["erased"]
    for surface in (
        "sessions",
        "notifications",
        "email_drafts",
        "connected_services",
        "service_credentials",
        "approvals",
        "automation_runs",
        "task_steps",
        "research_sources",
        "artifacts",
        "artifact_files",
        "wallets",
        "wallet_transactions",
        "telegram_accounts",
    ):
        assert surface in erased, f"closure did not report erasing {surface}"
    assert erased["artifact_files"] == 1
    assert not storage.exists(key)  # file actually removed
    assert body["anonymized"]["tasks_content_scrubbed"] == 1
    assert body["anonymized"]["scheduled_jobs_cancelled"] == 1
    assert "xp_ledger_entries" in body["retained"]
    assert any("recovery phrase" in d for d in body["disclosures"])

    # database state after closure
    user_rows = (
        (await session.execute(select(TelegramAccount))).scalars().all()
    )
    assert user_rows == []  # identity linkage gone
    task = (await session.execute(select(Task))).scalars().one()
    assert task.objective == ERASED_ON_CLOSURE
    assert task.deliverable is None
    job = (await session.execute(select(ScheduledJob))).scalars().one()
    assert job.status == "cancelled"
    assert job.task_template == {"objective": ERASED_ON_CLOSURE}
    assert job.next_run_at is None
    assert (await session.execute(select(Session))).scalars().all() == []
    assert (await session.execute(select(Notification))).scalars().all() == []
    assert (await session.execute(select(EmailDraft))).scalars().all() == []
    assert (await session.execute(select(ConnectedService))).scalars().all() == []
    assert (await session.execute(select(ServiceCredential))).scalars().all() == []
    assert (await session.execute(select(Wallet))).scalars().all() == []
    assert (await session.execute(select(WalletTransaction))).scalars().all() == []
    assert (await session.execute(select(Artifact))).scalars().all() == []
    # structural evidence survives
    ledger_count_after = len(
        (await session.execute(select(XpLedgerEntry))).scalars().all()
    )
    assert ledger_count_after == ledger_count_before
    assert (await session.execute(select(TaskEvent))).scalars().all() != []
    closed_audit = (
        await session.execute(
            select(AuditEvent).where(AuditEvent.event_type == "account.closed")
        )
    ).scalar_one()
    assert closed_audit.metadata_redacted["erased"] == erased


@pytest.mark.asyncio
async def test_closure_is_terminal(session):
    """Second closure over the SAME identity is refused (bearer-authed)."""
    from xp_core.models.entities import User

    user = User(display_name="Terminal User")
    session.add(user)
    await session.flush()
    token, _row = await create_session(session, user.id)
    await session.commit()

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {token}"}
        first = await client.post(
            "/api/v1/account/closure", json={"confirm": "CLOSE"}, headers=headers
        )
        assert first.status_code == 200
        second = await client.post(
            "/api/v1/account/closure", json={"confirm": "CLOSE"}, headers=headers
        )
        assert second.status_code == 401  # sessions erased with the account


@pytest.mark.asyncio
async def test_bearer_session_dead_after_closure(session):
    """Closure erases sessions: the bearer token cannot outlive the account."""
    from xp_core.models.entities import User

    user = User(display_name="Closing User")
    session.add(user)
    await session.flush()
    token, _row = await create_session(session, user.id)
    await session.commit()

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {token}"}
        ok = await client.post(
            "/api/v1/account/closure", json={"confirm": "CLOSE"}, headers=headers
        )
        assert ok.status_code == 200
        dead = await client.get("/api/v1/account/export", headers=headers)
        assert dead.status_code == 401
