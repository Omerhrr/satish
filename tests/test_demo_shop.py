"""Kaduna Kicks, the demo shop: a merchant website paid through Satish."""

from __future__ import annotations

import httpx
from httpx import ASGITransport, AsyncClient
from xp_core.config import Settings
from xp_core.services import handles as svc

from tests.test_handles import ADA, NET, Chain


async def test_demo_shop_checkout_and_order(session, dev_user, monkeypatch):
    from app.main import app

    chain = Chain()
    real = httpx.AsyncClient
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda **kw: real(**({"transport": httpx.MockTransport(chain.handler)} | kw)))
    import app.api.demo_shop as shop
    import app.api.v1.developers as dev
    import app.api.v1.handles as api_mod

    s = Settings(_env_file=None, onchain_min_conf=0, onchain_network=NET, mini_app_url="https://satish.rogan.live",
                 telegram_bot_token="123:abc")
    for mod in (api_mod, dev, shop):
        monkeypatch.setattr(mod, "get_settings", lambda: s)

    pub, signed = ADA
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = {"network": NET, "username": "shoeseller", "identity_pubkey": pub,
                "addresses": [{"address": a.address, "index": a.index, "signature": a.signature} for a in map(signed, range(1000, 1010))]}
        assert (await c.post("/api/v1/handles/claim", json=body)).status_code == 200

        page = await c.get("/api/demo-shop/")
        assert page.status_code == 200 and "KADUNA KICKS" in page.text
        prods = (await c.get("/api/demo-shop/products")).json()
        assert {p["id"] for p in prods["products"]} >= {"runners", "tote"}

        url = (await c.post("/api/v1/dev/demo-shop")).json()["url"]
        assert url.startswith("/api/demo-shop/#pass=")
        H = {"X-Shop-Pass": url.split("#pass=", 1)[1]}

        # No pass, or a forged one: no orders.
        items = {"items": [{"id": "runners", "qty": 2}, {"id": "tote", "qty": 1}], "city": "Kaduna"}
        assert (await c.post("/api/demo-shop/checkout", json=items)).status_code == 401
        assert (await c.post("/api/demo-shop/checkout", json=items, headers={"X-Shop-Pass": H["X-Shop-Pass"][:-2] + "00"})).status_code == 401

        r = await c.post("/api/demo-shop/checkout", json=items, headers=H)
        assert r.status_code == 200, r.text
        o = r.json()
        # Priced by the shop's own catalogue, plus delivery.
        assert o["payment"]["amount_sats"] == 2 * 2100 + 1800 + 300
        assert o["payment"]["username"] == "shoeseller" and o["payment"]["bitcoin_uri"].startswith("bitcoin:")
        assert o["request_sent"]["metadata"]["order_id"] == o["order_id"]

        st = await c.get(f"/api/demo-shop/orders/{o['payment']['id']}", headers=H)
        assert st.status_code == 200 and st.json()["status"] == "open"

        bad = await c.post("/api/demo-shop/checkout", json={"items": [{"id": "rolex", "qty": 1}]}, headers=H)
        assert bad.status_code == 422


def test_pass_expires():
    import time

    from fastapi import HTTPException

    from app.api.demo_shop import make_pass, read_pass

    assert read_pass(make_pass("u1", "testnet"))["u"] == "u1"
    try:
        read_pass(make_pass("u1", "testnet", ttl=-1))
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("expired pass accepted")
    assert time.time()
