"""KL-11 closure tests: operator identity in front of /ops/*.

Covers the honest decision table of app.deps.require_operator:
- Credential configured: REQUIRED everywhere (dev included), constant-time
  compared, accepted via X-Operator-Token or Authorization bearer; every
  grant and every denial lands in audit_events with NO credential material.
- No credential + DEV_MODE: allowed (unchanged local convenience).
- No credential + non-dev: 503, surfaces stay dark instead of opening.
- The fabrication walls (/xp/dev/grant) stay dev-only regardless of operator
  credentials, and the user auth wall is untouched.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import AuditEvent, User
from xp_core.services.ratelimit import IdentityCache
from xp_core.services.security import create_session

OPERATOR_TOKEN = "ops-operator-secret-token-0193"


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _audit_events(session) -> list[AuditEvent]:
    return list(
        (
            await session.execute(
                select(AuditEvent).where(AuditEvent.event_type.like("ops.%"))
            )
        )
        .scalars()
        .all()
    )


# decision row 2: no credential + DEV_MODE -> unchanged local convenience


async def test_dev_mode_without_credential_still_open(session, client):
    resp = await client.get("/api/v1/ops/observability")
    assert resp.status_code == 200
    # dev convenience grants no audit noise; ops traffic is operator-only
    assert await _audit_events(session) == []


# decision row 3: no credential + non-dev -> 503, dark, no audit spam


async def test_nondev_without_credential_refused_dark(session, client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", None)
    for method, path in (
        ("GET", "/api/v1/ops/observability"),
        ("GET", "/api/v1/ops/reconciliation/alerts"),
        ("POST", "/api/v1/ops/reconciliation/alerts/nonexistent/ack"),
        ("POST", "/api/v1/ops/reconciliation/alerts/nonexistent/resolve"),
    ):
        resp = await client.request(method, path)
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]
    # refusal is structural, not an incident per request: no ops audit rows
    assert await _audit_events(session) == []


# decision row 1: credential configured -> required everywhere


async def test_configured_credential_required_even_in_dev(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    resp = await client.get("/api/v1/ops/observability")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"


async def test_wrong_credential_denied_and_audited_without_secret(
    session, client, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    resp = await client.get(
        "/api/v1/ops/observability",
        headers={"Authorization": f"Bearer {OPERATOR_TOKEN}-wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "operator authentication required"
    assert OPERATOR_TOKEN not in resp.text
    events = await _audit_events(session)
    assert len(events) == 1
    denied = events[0]
    assert denied.event_type == "ops.access_denied"
    assert denied.actor_type == "admin"
    assert denied.metadata_redacted["reason"] == "invalid"
    assert denied.metadata_redacted["credential_fingerprint"] == IdentityCache.fingerprint(
        f"{OPERATOR_TOKEN}-wrong"
    )
    # the row itself carries no credential material
    assert OPERATOR_TOKEN not in (denied.metadata_redacted or {})


async def test_missing_credential_denied(session, client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    resp = await client.get("/api/v1/ops/observability")
    assert resp.status_code == 401
    events = await _audit_events(session)
    assert events[0].metadata_redacted["reason"] == "missing"
    assert events[0].metadata_redacted["credential_fingerprint"] is None


async def test_correct_credential_granted_via_bearer_and_audited(
    session, client, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    resp = await client.get(
        "/api/v1/ops/observability",
        headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["rate_limit_backend"] == "memory"
    events = await _audit_events(session)
    assert len(events) == 1
    granted = events[0]
    assert granted.event_type == "ops.access_granted"
    assert granted.metadata_redacted == {
        "method": "GET",
        "source": "bearer",
    }
    assert OPERATOR_TOKEN not in resp.text


async def test_correct_credential_via_dedicated_header(session, client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    resp = await client.get(
        "/api/v1/ops/reconciliation/alerts",
        headers={"X-Operator-Token": OPERATOR_TOKEN},
    )
    assert resp.status_code == 200
    events = await _audit_events(session)
    assert events[0].metadata_redacted["source"] == "x-operator-token"


async def test_operator_credential_cannot_touch_user_endpoints(
    session, client, monkeypatch
):
    """The operator credential authorizes /ops only: it is not a user session."""
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    resp = await client.get(
        "/api/v1/auth/sessions", headers={"X-Operator-Token": OPERATOR_TOKEN}
    )
    assert resp.status_code == 401  # user auth wall untouched by the ops key


async def test_dev_grant_still_dev_only_even_with_operator_credential(
    session, client, monkeypatch
):
    """Fabrication walls stay up: an operator can run the ops queue, never
    mint XP balances outside dev."""
    settings = get_settings()
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "ops_operator_token", OPERATOR_TOKEN)
    user = User(display_name="Wall Probe")
    session.add(user)
    await session.flush()
    token, _row = await create_session(session, user.id)
    resp = await client.post(
        "/api/v1/xp/dev/grant",
        json={"amount_xp": 100, "reason": "operator probe"},
        headers={"Authorization": f"Bearer {token}", "X-Operator-Token": OPERATOR_TOKEN},
    )
    assert resp.status_code == 403
    assert "dev grants are disabled" in resp.json()["detail"]
