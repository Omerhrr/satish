"""Price alerts fire once; savings goals celebrate once."""

from __future__ import annotations

from sqlalchemy import select
from xp_core.models.entities import Notification
from xp_core.services.relay import render_notification_text

from app.api.v1.money import sweep_price_alerts
from tests.test_agent_runtime import client  # noqa: F401


async def test_price_alert_fires_once(client, session):
    a = (await client.post("/api/v1/alerts/price", json={"currency": "ngn", "direction": "above", "target": 150_000_000})).json()
    assert a["active"] and a["currency"] == "NGN"
    assert await sweep_price_alerts(session, {"NGN": 149_000_000}) == 0
    assert await sweep_price_alerts(session, {"NGN": 151_000_000}) == 1
    assert await sweep_price_alerts(session, {"NGN": 152_000_000}) == 0  # once only
    n = (await session.execute(select(Notification).where(Notification.kind == "price.alert"))).scalar_one()
    text = render_notification_text(n, None)
    assert "₦151,000,000" in text and "above" in text and "₦150,000,000" in text
    listed = (await client.get("/api/v1/alerts/price")).json()
    assert listed[0]["active"] is False


async def test_goals(client, session):
    g = (await client.post("/api/v1/goals", json={"name": "School fees", "target_amount": 50000, "currency": "NGN"})).json()
    assert (await client.get("/api/v1/goals")).json()[0]["name"] == "School fees"
    await client.post(f"/api/v1/goals/{g['id']}/reached")
    await client.post(f"/api/v1/goals/{g['id']}/reached")
    ns = (await session.execute(select(Notification).where(Notification.kind == "savings.goal_reached"))).scalars().all()
    assert len(ns) == 1 and "School fees" in render_notification_text(ns[0], None)
    assert (await client.delete(f"/api/v1/goals/{g['id']}")).status_code == 204
