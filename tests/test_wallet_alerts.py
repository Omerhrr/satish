"""Opt-in Telegram alerts when the on-device wallet receives bitcoin."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from xp_core.config import Settings
from xp_core.models.entities import Notification, WatchedAddress
from xp_core.services import handles as handles_svc
from xp_core.services import wallet_alerts as svc
from xp_core.services.relay import render_notification_text

from tests.test_handles import ADA

NET = "testnet"
ADDR = ADA[1](0).address
SETTINGS = Settings(_env_file=None)


class Chain:
    """Fake Esplora: address -> list of (txid, value, confirmed)."""

    def __init__(self):
        self.txs: dict[str, list[tuple[str, int, bool]]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        addr = request.url.path.split("/address/")[1].split("/")[0]
        return httpx.Response(
            200,
            json=[
                {"txid": t, "status": {"confirmed": c}, "vout": [{"scriptpubkey_address": addr, "value": v}]}
                for t, v, c in self.txs.get(addr, [])
            ],
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def notes(session) -> list[Notification]:
    return (await session.execute(select(Notification).order_by(Notification.created_at))).scalars().all()


async def test_off_by_default_and_nothing_watched(session, dev_user):
    assert await svc.status(session, dev_user, NET) == {"enabled": False, "watched": 0}
    assert await svc.add_addresses(session, dev_user, NET, [ADDR]) == 0  # ignored until switched on


async def test_received_then_confirmed_once_each(session, dev_user):
    chain = Chain()
    chain.txs[ADDR] = [("old" + "0" * 61, 9_000, True)]  # history from before alerts were on
    await svc.set_enabled(session, dev_user, NET, True, [ADDR])
    async with chain.client() as c:
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 0  # baseline: no replay
        chain.txs[ADDR].append(("new" + "0" * 61, 25_000, False))
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 1
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 0  # nothing new
        chain.txs[ADDR][-1] = ("new" + "0" * 61, 25_000, True)
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 1
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 0
    got = await notes(session)
    assert [n.kind for n in got] == ["wallet.received", "wallet.confirmed"]
    assert "receiving 25,000 sats (test coins)" in render_notification_text(got[0], None)
    assert "now confirmed" in render_notification_text(got[1], None)


async def test_turning_off_forgets_addresses_and_stops_messages(session, dev_user):
    chain = Chain()
    await svc.set_enabled(session, dev_user, NET, True, [ADDR])
    async with chain.client() as c:
        await svc.sweep(session, SETTINGS, client=c)
        await svc.set_enabled(session, dev_user, NET, False, [])
        chain.txs[ADDR] = [("x" * 64, 1_000, False)]
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 0
    assert (await session.execute(select(WatchedAddress))).scalars().all() == []


async def test_rejects_wrong_network_addresses(session, dev_user):
    await svc.set_enabled(session, dev_user, NET, True, [])
    with pytest.raises(svc.AlertError):
        await svc.add_addresses(session, dev_user, NET, ["bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"])


async def test_username_payments_are_watched_but_request_addresses_are_not(session, dev_user):
    pub, signed = ADA
    h = await handles_svc.claim(
        session, dev_user, network=NET, username="alerty", identity_pubkey=pub, addresses=[signed(i) for i in range(1000, 1004)]
    )
    paid_by_name, _ = await handles_svc.issue_address(session, h)
    req = await handles_svc.create_request(session, dev_user, network=NET, amount_sats=5_000, note="rice")
    await session.commit()
    await svc.set_enabled(session, dev_user, NET, True, [])
    chain = Chain()
    async with chain.client() as c:
        await svc.sweep(session, SETTINGS, client=c)  # baseline
        chain.txs[paid_by_name.address] = [("a" * 64, 3_000, False)]
        chain.txs[req.address] = [("b" * 64, 5_000, False)]
        assert (await svc.sweep(session, SETTINGS, client=c))["messages"] == 1
    got = await notes(session)
    assert len(got) == 1 and got[0].payload["amount_sats"] == 3_000


async def test_api_and_closure(session, dev_user):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/wallet/alerts", params={"network": NET})
        assert r.json() == {"enabled": False, "watched": 0}
        r = await c.put("/api/v1/wallet/alerts", json={"network": NET, "enabled": True, "addresses": [ADDR]})
        assert r.json() == {"enabled": True, "watched": 1}
        r = await c.post("/api/v1/wallet/alerts/addresses", json={"network": NET, "addresses": [ADA[1](1).address, ADDR]})
        assert r.json()["watched"] == 2
        r = await c.post("/api/v1/wallet/alerts/addresses", json={"network": NET, "addresses": ["nonsense-address-here-xx"]})
        assert r.status_code == 422

    from xp_core.config import get_settings
    from xp_core.models.entities import User
    from xp_core.services.closure import close_account

    owner_id = (await session.execute(select(WatchedAddress.user_id))).scalars().first()
    await close_account(session, await session.get(User, owner_id), get_settings())
    assert (await session.execute(select(WatchedAddress))).scalars().all() == []
