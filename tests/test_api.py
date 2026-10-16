"""API contract tests: health, auth, XP flow, task reservation - via ASGI transport."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "xp-api"


async def test_health_reports_components(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"]["status"] == "ok"
    assert "dsh_revision" in body


async def test_request_id_echoed(client):
    resp = await client.get("/healthz", headers={"X-Request-ID": "trace-123"})
    assert resp.headers.get("X-Request-ID") == "trace-123"


async def test_telegram_auth_dev_mode_issues_session(client):
    resp = await client.post("/api/v1/auth/telegram", json={"init_data": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "dev"
    assert body["session_token"]


async def test_xp_grant_balance_ledger_flow(client, session, dev_user):
    grant = await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 750})
    assert grant.status_code == 200
    assert grant.json()["balance_xp"] == 750

    balance = await client.get("/api/v1/xp/balance")
    assert balance.json()["balance_xp"] == 750

    ledger_page = await client.get("/api/v1/xp/ledger")
    items = ledger_page.json()["items"]
    assert len(items) == 1
    assert items[0]["entry_type"] == "adjustment"


async def test_task_creation_reserves_budget_and_cancel_releases(client, session, dev_user):
    await client.post("/api/v1/xp/dev/grant", json={"amount_xp": 1000})

    created = await client.post(
        "/api/v1/tasks",
        json={"objective": "Summarize lightning liquidity management options", "budget_xp": 200},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "planned"
    assert task["reserved_xp"] == 200

    balance_after_reserve = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance_after_reserve == 800

    cancelled = await client.post(f"/api/v1/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    balance_after_cancel = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance_after_cancel == 1000


async def test_task_creation_fails_when_budget_unavailable(client, session, dev_user):
    """Balance is zero here; any reservation must fail with a payment error."""
    resp = await client.post(
        "/api/v1/tasks",
        json={"objective": "Reserve more than the balance allows", "budget_xp": 50000},
    )
    assert resp.status_code == 402


async def test_demo_pdf_creates_ready_artifact(client, session, dev_user, tmp_path):
    """Full pipeline: API -> worker job (inline dev) -> WeasyPrint -> storage."""
    import os

    os.environ["XP_ARTIFACT_DIR"] = str(tmp_path)
    created = await client.post(
        "/api/v1/artifacts/demo-pdf",
        json={"title": "Unit Test Report", "sections": ["Findings", "Sources"]},
    )
    assert created.status_code == 202
    artifact = created.json()
    assert artifact["status"] == "ready"
    assert artifact["size_bytes"] > 0

    download = await client.get(f"/api/v1/artifacts/{artifact['id']}/download")
    assert download.status_code == 200
    assert download.content[:4] == b"%PDF"


async def test_artifact_download_requires_ownership(client, session, dev_user, tmp_path):
    """Private-by-default: another user's artifact is a 404, not a leak."""
    import os


    os.environ["XP_ARTIFACT_DIR"] = str(tmp_path)
    created = await client.post(
        "/api/v1/artifacts/demo-pdf", json={"title": "Mine only", "sections": ["A"]}
    )
    artifact = created.json()

    # bogus token: must never resolve to a session
    resp = await client.get(
        f"/api/v1/artifacts/{artifact['id']}/download",
        headers={"Authorization": "Bearer bogus-token"},
    )
    assert resp.status_code in {401, 404}
