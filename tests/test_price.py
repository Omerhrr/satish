"""BTC/NGN display price: cached, survives source outages, hides when unknown."""

from __future__ import annotations

import httpx
import pytest


@pytest.fixture(autouse=True)
def clear_cache():
    import app.api.v1.price as price

    price._cache.clear()
    yield
    price._cache.clear()


async def test_price_cached_and_survives_outage(monkeypatch):
    import app.api.v1.price as price

    calls = {"n": 0}

    def ok(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.params["vs_currencies"] == "ngn,usd"
        return httpx.Response(200, json={"bitcoin": {"ngn": 160_000_000, "usd": 100_000}})

    p = await price.current_price(httpx.MockTransport(ok))
    assert p["btc_ngn"] == 160_000_000
    await price.current_price(httpx.MockTransport(ok))
    assert calls["n"] == 1  # served from cache

    price._cache["at"] -= price.PRICE_TTL_SECONDS + 1  # expire it
    p = await price.current_price(httpx.MockTransport(lambda r: httpx.Response(500)))
    assert p["btc_ngn"] == 160_000_000  # last good price kept


async def test_endpoint_503_without_any_price(monkeypatch, session, dev_user):
    import app.api.v1.price as price
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    async def failing(transport=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(price, "_fetch", failing)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/v1/price/btc")).status_code == 503
        price._cache.update(btc_ngn=1.5e8, btc_usd=1e5, at=__import__("time").time())
        r = await c.get("/api/v1/price/btc")
        assert r.status_code == 200 and r.json()["btc_ngn"] == 1.5e8


async def test_rates_cover_every_currency():
    import httpx

    from app.api.v1 import price

    def handler(request: httpx.Request) -> httpx.Response:
        if "coingecko" in request.url.host:
            return httpx.Response(200, json={"bitcoin": {"usd": 100_000, "ngn": 160_000_000}})
        return httpx.Response(200, json={"rates": {"USD": 1, "GHS": 15.5, "KES": 129, "NGN": 1500}})

    price._rates.clear()
    r = await price.current_rates(transport=httpx.MockTransport(handler))
    btc = r["btc"]
    assert btc["NGN"] == 160_000_000  # market rate from CoinGecko, not the official one
    assert btc["GHS"] == 100_000 * 15.5 and btc["KES"] == 100_000 * 129
    price._rates.clear()
