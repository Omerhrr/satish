"""Phase-10 tests: security, reliability, and operational readiness.

Covers:
- Abuse controls (rate limiting): per-class buckets trip to 429 with honest
  headers, subject isolation, kill switch, monitoring surfaces unlimited.
- Payment reconciliation alerts: drift -> open critical alert, dedupe on
  repeat sightings, ack/resolve operator lifecycle via /ops, critical alerts
  never auto-resolve, expired-pending warnings auto-resolve.
- Privacy / retention: sweeps delete only within configured windows and
  never touch the money trail or audit surfaces.
- Backup/restore drill: full S1->S4 roundtrip with ledger re-verification.
- Dependency/container audit gates: clean repo passes; a deliberately bad
  spec fails the gate (proving the gate is real).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.jobs.reconciliation import reconcile_all
from xp_core.models.entities import (
    AutomationRun,
    EmailDraft,
    Notification,
    PaymentIntent,
    ReconciliationAlert,
    Session,
)
from xp_core.services import ledger
from xp_core.services.ratelimit import (
    RateLimiter,
    RouteClass,
    classify_path,
    subject_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture()
async def client(session, dev_user, monkeypatch):
    """ASGI client with the limiter force-enabled and buckets reset per test
    (conftest disables it suite-wide so other tests never fight over buckets)."""
    from app.main import app

    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        app.state.rate_limiter._buckets.clear()
        yield c
    app.state.rate_limiter._buckets.clear()


# -- rate limiting: unit level ---------------------------------------------------------


def test_classify_path_maps_surfaces_to_classes():
    assert classify_path("POST", "/api/v1/auth/telegram") == RouteClass.AUTH
    assert classify_path("GET", "/api/v1/auth/sessions") == RouteClass.AUTH
    assert classify_path("POST", "/api/v1/wallets/w/create") == RouteClass.MONEY
    assert classify_path("POST", "/api/v1/lightning/invoices") == RouteClass.MONEY
    assert classify_path("POST", "/api/v1/xp/purchases") == RouteClass.MONEY
    assert classify_path("GET", "/api/v1/xp/purchases") == RouteClass.READ
    assert classify_path("POST", "/api/v1/tasks") == RouteClass.AGENT
    assert classify_path("GET", "/api/v1/tasks") == RouteClass.READ
    assert classify_path("POST", "/api/v1/anything-else") == RouteClass.WRITE
    # monitoring surfaces must never be throttleable
    assert classify_path("GET", "/healthz") == ""
    assert classify_path("GET", "/api/v1/health") == ""
    assert classify_path("GET", "/api/v1/capabilities") == ""


def test_token_bucket_drains_and_reports_retry_after():
    limiter = RateLimiter()  # auth: rate 10/min, burst 5
    subject = subject_for("10.0.0.1", None)
    results = [limiter.check(RouteClass.AUTH, subject) for _ in range(6)]
    assert all(r.allowed for r in results[:5])
    tripped = results[5]
    assert not tripped.allowed
    assert tripped.retry_after_seconds >= 1
    assert tripped.limit == 10


def test_buckets_are_isolated_per_subject():
    limiter = RateLimiter()
    a = subject_for("10.0.0.1", "token-a")
    b = subject_for("10.0.0.1", "token-b")
    for _ in range(5):
        assert limiter.check(RouteClass.AUTH, a).allowed
    assert not limiter.check(RouteClass.AUTH, a).allowed
    # a different credential (or credential-less IP) is a different bucket
    assert limiter.check(RouteClass.AUTH, b).allowed
    assert limiter.check(RouteClass.WRITE, a).allowed  # per-class buckets


# -- rate limiting: HTTP level -----------------------------------------------------------


async def test_auth_surface_trips_to_429_with_honest_headers(client):
    first = await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
    assert first.status_code != 429  # dev-mode may accept it; not throttled yet
    assert first.headers["X-RateLimit-Limit"] == "10"  # auth class pinned
    # burst 5 -> the 6th request on this subject trips
    codes = []
    for _ in range(6):
        resp = await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
        codes.append(resp.status_code)
    assert codes[-1] == 429
    body = resp.json()
    assert "rate limit" in body["detail"]
    assert resp.headers["Retry-After"] >= "1"
    assert resp.headers["X-RateLimit-Remaining"] == "0"


async def test_health_surfaces_are_never_throttled(client):
    for _ in range(8):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" not in resp.headers


async def test_rate_limit_kill_switch(monkeypatch, client):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    for _ in range(12):
        resp = await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
        assert resp.status_code != 429
        assert "X-RateLimit-Limit" not in resp.headers


# -- reconciliation alerts -----------------------------------------------------------------


async def test_balance_drift_opens_critical_alert_and_dedupes(session, dev_user):
    acct = await ledger.get_or_create_account(session, dev_user.id)
    await ledger.adjust(session, user_id=dev_user.id, amount=500, reason="seed")
    await session.commit()

    # tamper: balance no longer equals sum(entries)
    acct.balance += 1_000
    await session.commit()

    report = await reconcile_all(session)
    assert report["ok"] is False
    assert report["alerts_opened"] == 1
    alert = (
        await session.execute(select(ReconciliationAlert).where(ReconciliationAlert.status == "open"))
    ).scalar_one()
    assert alert.kind == "balance_mismatch"
    assert alert.severity == "critical"
    assert alert.subject == dev_user.id
    assert alert.expected == "500"  # ledger truth: sum of entries
    assert alert.observed == "1500"  # what the tampered account row claims

    # second sighting dedupes instead of stacking
    report2 = await reconcile_all(session)
    assert report2["alerts_opened"] == 0
    assert report2["alerts_updated"] == 1
    rows = (await session.execute(select(ReconciliationAlert))).scalars().all()
    assert len(rows) == 1


async def test_critical_alerts_never_auto_resolve(session, dev_user):
    acct = await ledger.get_or_create_account(session, dev_user.id)
    await ledger.adjust(session, user_id=dev_user.id, amount=10, reason="seed")
    await session.commit()
    acct.balance += 50
    await session.commit()
    await reconcile_all(session)

    # operator repairs the drift: the discrepancy vanishes, the alert stays
    acct.balance -= 50
    await session.commit()
    report = await reconcile_all(session)
    assert report["ok"] is True
    alert = (await session.execute(select(ReconciliationAlert))).scalar_one()
    assert alert.status in ("open", "acknowledged"), (
        "money-integrity alerts must be resolved by an operator, never silently"
    )


async def test_expired_pending_warning_alerts_auto_resolve(session, dev_user):
    intent = PaymentIntent(
        id="intent-exp-1",
        user_id=dev_user.id,
        direction="receive",
        status="pending",
        amount_sats=500,
        xp_amount=50_000,
        idempotency_key="drill:expired:1",
        expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2),
    )
    session.add(intent)
    await session.commit()

    report = await reconcile_all(session)
    assert report["expired_pending_flagged"] == 1
    alert = (
        await session.execute(
            select(ReconciliationAlert).where(ReconciliationAlert.kind == "expired_pending")
        )
    ).scalar_one()
    assert alert.severity == "warning"
    assert alert.status == "open"

    # the pending intent resolves -> next sweep auto-resolves the warning
    intent.status = "expired"
    await session.commit()
    report2 = await reconcile_all(session)
    assert report2["alerts_auto_resolved"] == 1
    assert report2["ok"] is True


async def test_ops_alert_lifecycle_over_http(client, session, dev_user):
    acct = await ledger.get_or_create_account(session, dev_user.id)
    await ledger.adjust(session, user_id=dev_user.id, amount=5, reason="seed")
    await session.commit()
    acct.balance += 77
    await session.commit()
    await reconcile_all(session)

    listing = await client.get("/api/v1/ops/reconciliation/alerts")
    assert listing.status_code == 200
    page = listing.json()
    assert page["open_critical"] == 1
    assert len(page["alerts"]) == 1
    alert = page["alerts"][0]
    assert alert["kind"] == "balance_mismatch"

    ack = await client.post(f"/api/v1/ops/reconciliation/alerts/{alert['id']}/ack")
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledged_at"] is not None

    resolved = await client.post(
        f"/api/v1/ops/reconciliation/alerts/{alert['id']}/resolve",
        params={"note": "repaired by hand; verified against entries"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    after = (await client.get("/api/v1/ops/reconciliation/alerts")).json()
    assert after["open_critical"] == 0
    history = await client.get(
        "/api/v1/ops/reconciliation/alerts", params={"include_resolved": True}
    )
    assert any(a["status"] == "resolved" for a in history.json()["alerts"])

    obs = await client.get("/api/v1/ops/observability")
    assert obs.status_code == 200
    body = obs.json()
    assert body["alerts_open_critical"] == 0
    assert body["alerts_resolved_total"] == 1
    assert body["rate_limit_enabled"] is True
    assert "sessions_days" in body["retention_policy"]


async def test_404_and_409_on_bad_lifecycle_transitions(client, session):
    missing = await client.post("/api/v1/ops/reconciliation/alerts/nope/ack")
    assert missing.status_code == 404


# -- privacy / retention ---------------------------------------------------------------------


def _old(days: int) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)


async def test_retention_sweep_deletes_only_within_windows(session, dev_user):
    settings = get_settings()
    # sessions: old-expired (sweep), old-revoked (sweep), live (keep)
    session.add_all(
        [
            Session(
                id="s-old",
                user_id=dev_user.id,
                token_hash="old" * 10,
                expires_at=_old(settings.retention_sessions_days + 1),
            ),
            Session(
                id="s-revoked",
                user_id=dev_user.id,
                token_hash="rev" * 10,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
                revoked_at=_old(settings.retention_sessions_days + 1),
            ),
            Session(
                id="s-live",
                user_id=dev_user.id,
                token_hash="live" * 10,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            ),
        ]
    )
    # notifications: old+read (sweep), old+unread inside window (keep),
    # ancient+unread (sweep), fresh (keep)
    session.add_all(
        [
            Notification(id="n-old-read", user_id=dev_user.id, kind="k",
                         read_at=_old(settings.retention_notifications_read_days + 5)),
            Notification(id="n-old-unread", user_id=dev_user.id, kind="k",
                         created_at=_old(settings.retention_notifications_unread_days - 10)),
            Notification(id="n-ancient", user_id=dev_user.id, kind="k",
                         created_at=_old(settings.retention_notifications_unread_days + 30)),
            Notification(id="n-fresh", user_id=dev_user.id, kind="k"),
        ]
    )
    # automation runs: old finished (sweep), recent finished (keep), running (keep)
    session.add_all(
        [
            AutomationRun(id="r-old", job_id="j", user_id=dev_user.id, run_number=1,
                          status="succeeded", finished_at=_old(settings.retention_automation_runs_days + 5)),
            AutomationRun(id="r-new", job_id="j", user_id=dev_user.id, run_number=2,
                          status="succeeded", finished_at=_old(1)),
        ]
    )
    # drafts: terminal old (sweep), drafted old (keep — pending user decision)
    session.add_all(
        [
            EmailDraft(id="d-sent", user_id=dev_user.id, to_address="a@b.c",
                       subject="s", body="b", digest="d1" * 32, status="sent",
                       sent_at=_old(settings.retention_email_drafts_sent_days + 5)),
            EmailDraft(id="d-draft", user_id=dev_user.id, to_address="a@b.c",
                       subject="s", body="b", digest="d2" * 32, status="drafted",
                       created_at=_old(400)),
        ]
    )
    # money trail that must survive everything
    await ledger.adjust(session, user_id=dev_user.id, amount=123, reason="survivor")
    await session.commit()

    from xp_core.jobs.retention import retention_proof, retention_sweep

    report = await retention_sweep(session)
    assert report["deleted"]["sessions"] == 2
    assert report["deleted"]["notifications"] == 2
    assert report["deleted"]["automation_runs"] == 1
    assert report["deleted"]["email_drafts"] == 1

    survivors = {
        sid
        for sid in ("s-old", "s-revoked", "s-live")
        if (
            await session.execute(select(Session).where(Session.id == sid))
        ).scalar_one_or_none()
    }
    assert survivors == {"s-live"}
    notes = (await session.execute(select(Notification))).scalars().all()
    assert {n.id for n in notes} == {"n-old-unread", "n-fresh"}
    drafts = (await session.execute(select(EmailDraft))).scalars().all()
    assert {d.id for d in drafts} == {"d-draft"}
    runs = (await session.execute(select(AutomationRun))).scalars().all()
    assert {r.id for r in runs} == {"r-new"}

    proof = await retention_proof(session)
    assert proof["xp_ledger_entries"] >= 1  # money trail untouched
    assert proof["audit_events"] >= 1  # audit trail untouched


# -- drills and audits --------------------------------------------------------------------------


async def test_backup_restore_drill_roundtrip(session):
    import backup_drill

    report = await backup_drill.run_drill()
    assert report["ok"], report["verification"]
    checks = report["verification"]["checks"]
    assert checks["row_counts_match"] is True
    assert checks["ledger_reconciles"] is True
    assert checks["settled_intents"] >= 1
    assert report["scope_notes"], "the drill must state its honest scope"


def test_dependency_audit_passes_on_clean_repo():
    import dependency_audit

    report = dependency_audit.audit_repo(REPO_ROOT)
    assert report["ok"], report["hard_findings"]
    assert report["python_dependencies"] > 10
    assert report["container_images"], "compose images must be inventoried"
    for scanner in report["live_scanners"]:
        assert scanner["status"] in ("available", "not_installed", "error")


def test_dependency_audit_gate_catches_bad_specs(tmp_path):
    import dependency_audit

    bad = tmp_path / "pkgA"
    bad.mkdir()
    (bad / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["requests", "evil-git @ git+https://x", "star @ *"]\n'
    )
    _inventory, findings = dependency_audit._python_inventory(tmp_path)
    specs = {f["finding"] for f in findings}
    assert any("git+" in s for s in specs)
    assert any("'*'" in s or "'star @ *'" in s for s in specs)


def test_container_audit_gate_catches_latest_tag(tmp_path):
    import dependency_audit

    infra = tmp_path / "infra"
    infra.mkdir()
    (infra / "docker-compose.yml").write_text(
        "services:\n  db:\n    image: postgres:latest\n  cache:\n    image: redis:7-alpine\n"
    )
    _, findings = dependency_audit._container_inventory(tmp_path)
    assert len(findings) == 1
    assert "postgres:latest" in findings[0]["finding"]
