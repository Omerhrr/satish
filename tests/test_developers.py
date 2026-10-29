"""Developer API: keys, payment requests via the API, signed webhooks."""

from __future__ import annotations

import json

import httpx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from xp_core.config import Settings
from xp_core.models.entities import PaymentRequest, WebhookDelivery
from xp_core.services import handles as svc
from xp_core.services import webhooks as wh

from tests.test_handles import ADA, NET, Chain


async def test_keys_payment_requests_and_webhooks(session, dev_user, monkeypatch):
    from app.main import app

    chain = Chain()
    real = httpx.AsyncClient
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda **kw: real(**({"transport": httpx.MockTransport(chain.handler)} | kw)))
    import app.api.v1.developers as dev
    import app.api.v1.handles as api_mod

    s = Settings(_env_file=None, onchain_min_conf=0, mini_app_url="https://satish.rogan.live", telegram_bot_username="SatishBot")
    monkeypatch.setattr(api_mod, "get_settings", lambda: s)
    monkeypatch.setattr(dev, "get_settings", lambda: s)
    monkeypatch.setattr(wh, "check_url", lambda url, resolve=True: url)  # no DNS in tests

    pub, signed = ADA
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = {"network": NET, "username": "shop", "identity_pubkey": pub,
                "addresses": [{"address": a.address, "index": a.index, "signature": a.signature} for a in map(signed, range(1000, 1010))]}
        assert (await c.post("/api/v1/handles/claim", json=body)).status_code == 200

        k = (await c.post("/api/v1/dev/keys", json={"name": "My shop", "network": "testnet"})).json()
        secret = k["secret"]
        assert secret.startswith("sk_test_") and k["prefix"] == secret[:12]
        assert all(x["secret"] is None for x in (await c.get("/api/v1/dev/keys")).json())  # shown once

        hook = (await c.post("/api/v1/dev/webhooks", json={"url": "https://shop.example.com/satish"})).json()
        assert hook["secret"].startswith("whsec_")

        H = {"Authorization": f"Bearer {secret}"}
        r = await c.post("/api/v1/dev/payment-requests", headers=H,
                         json={"amount_sats": 25_000, "note": "Order 42", "metadata": {"order": "42"}})
        assert r.status_code == 201, r.text
        pr = r.json()
        assert pr["pay_url"] == f"https://satish.rogan.live/pay/{pr['id']}"
        assert pr["telegram_url"] == f"https://t.me/SatishBot?start=pay_{pr['id']}"
        assert pr["bitcoin_uri"].startswith(f"bitcoin:{pr['address']}?amount=0.00025")
        assert pr["metadata"] == {"order": "42"} and pr["status"] == "open"

        assert (await c.post("/api/v1/dev/payment-requests", headers={"Authorization": "Bearer sk_test_nope"},
                             json={"amount_sats": 1000})).status_code == 401
        assert (await c.post("/api/v1/dev/payment-requests", headers=H,
                             json={"amount_sats": 1000, "network": "mainnet"})).status_code == 422

        # paid on chain -> webhook queued with the developer's metadata
        chain.paid[pr["address"]] = 25_000
        row = await session.get(PaymentRequest, pr["id"])
        row.checked_at = None
        await session.commit()
        got = (await c.get(f"/api/v1/dev/payment-requests/{pr['id']}", headers=H)).json()
        assert got["status"] == "paid"
        d = (await session.execute(select(WebhookDelivery).where(WebhookDelivery.event == "request.paid"))).scalar_one()
        assert d.payload["data"]["metadata"] == {"order": "42"}

        seen = {}

        def receiver(request: httpx.Request) -> httpx.Response:
            seen["sig"] = request.headers["Satish-Signature"]
            seen["body"] = request.content
            return httpx.Response(200)

        out = await wh.deliver_pending(session, transport=httpx.MockTransport(receiver), resolve=False)
        assert out["delivered"] == 1
        assert wh.verify(hook["secret"], seen["body"], seen["sig"])
        assert not wh.verify("whsec_wrong", seen["body"], seen["sig"])
        assert json.loads(seen["body"])["data"]["id"] == pr["id"]

        # revoked keys stop working
        assert (await c.delete(f"/api/v1/dev/keys/{k['id']}")).status_code == 204
        assert (await c.get("/api/v1/dev/payment-requests", headers=H)).status_code == 401


async def test_failed_delivery_retries_then_gives_up(session, dev_user, monkeypatch):
    from xp_core.models.entities import WebhookEndpoint

    ep = WebhookEndpoint(user_id=dev_user.id, url="https://x.example.com/h", secret=wh.new_secret(), events=["request.paid"])
    session.add(ep)
    await session.commit()
    await wh.queue_event(session, dev_user.id, "request.paid", {"id": "r1"})
    await session.commit()
    down = httpx.MockTransport(lambda r: httpx.Response(500))
    await wh.deliver_pending(session, transport=down, resolve=False)
    d = (await session.execute(select(WebhookDelivery))).scalar_one()
    assert d.status == "pending" and d.attempts == 1 and d.last_status_code == 500
    for _ in range(len(wh.BACKOFF)):
        d.next_attempt_at = d.created_at
        await session.commit()
        await wh.deliver_pending(session, transport=down, resolve=False)
    await session.refresh(d)
    assert d.status == "failed"


def test_webhook_urls_must_be_public_https():
    import pytest

    for bad in ["http://shop.example.com/h", "https://localhost/h", "https://user:pw@example.com/h", "https://10.0.0.5/h", "https://127.0.0.1/h"]:
        with pytest.raises(wh.WebhookUrlError):
            wh.check_url(bad)


async def test_lightning_request_paid_webhook_and_forward(session, dev_user, monkeypatch):
    from app.main import app
    from app.services import dev_lightning, tk_lightning
    from xp_core.models.entities import WalletHandle

    class Payee:
        def __init__(self):
            self.paid, self.sent = set(), []

        async def create_invoice(self, amount_sats, description, expiry_secs):
            return f"lnbcrt{amount_sats}n1devfake"

        async def paid_invoices(self, since_unix):
            return self.paid

        async def forward(self, destination, amount_sats, key):
            self.sent.append((destination, amount_sats, key))
            return "pay-1"

    payee = Payee()
    tk_lightning.set_wallet(payee)
    try:
        import app.api.v1.developers as dev
        import app.api.v1.handles as api_mod

        s = Settings(_env_file=None, mini_app_url="https://satish.rogan.live", tk_lightning_network="regtest")
        monkeypatch.setattr(api_mod, "get_settings", lambda: s)
        monkeypatch.setattr(dev, "get_settings", lambda: s)
        pub, signed = ADA
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = {"network": NET, "username": "lnshop", "identity_pubkey": pub,
                    "addresses": [{"address": a.address, "index": a.index, "signature": a.signature} for a in map(signed, range(1000, 1005))]}
            assert (await c.post("/api/v1/handles/claim", json=body)).status_code == 200
            h = (await session.execute(select(WalletHandle).where(WalletHandle.username == "lnshop"))).scalar_one()
            h.spark_address, h.spark_network = "sprt1devspark", "regtest"
            await session.commit()

            monkeypatch.setattr(wh, "check_url", lambda url, resolve=True: url)
            assert (await c.post("/api/v1/dev/webhooks", json={"url": "https://shop.example.com/h"})).status_code == 201
            pr = (await c.post("/api/v1/dev/payment-requests", json={"amount_sats": 2100, "note": "Coffee"})).json()
            assert pr["lightning_invoice"] == "lnbcrt2100n1devfake" and pr["methods"] == ["onchain", "lightning"]
            assert pr["lightning_uri"].startswith("lightning:") and "lightning=lnbcrt2100n1devfake" in pr["bitcoin_uri"]
            # the public pay page shows the invoice too
            assert (await c.get(f"/api/v1/requests/{pr['id']}")).json()["lightning_invoice"] == pr["lightning_invoice"]

            payee.paid.add(pr["lightning_invoice"])
            got = (await c.get(f"/api/v1/dev/payment-requests/{pr['id']}")).json()
            assert got["status"] == "paid" and got["paid_via"] == "lightning" and got["forward_status"] == "pending"
            d = (await session.execute(select(WebhookDelivery).where(WebhookDelivery.event == "request.paid"))).scalars().all()
            assert [x.payload["data"]["paid_via"] for x in d if x.payload["data"]["id"] == pr["id"]] == ["lightning"]

            out = await dev_lightning.forward_pending(session, s)
            assert out == {"forwarded": 1, "failed": 0}
            assert payee.sent[0][0] == "sprt1devspark" and payee.sent[0][1] == 2100
            again = (await c.get(f"/api/v1/dev/payment-requests/{pr['id']}")).json()
            assert again["forward_status"] == "sent"

            # no Lightning wallet opened -> Bitcoin only, with a warning; lightning-only is refused
            h.spark_address = None
            await session.commit()
            b = (await c.post("/api/v1/dev/payment-requests", json={"amount_sats": 2100})).json()
            assert "lightning_invoice" not in b and b["warning"].startswith("Bitcoin only")
            only = await c.post("/api/v1/dev/payment-requests", json={"amount_sats": 2100, "methods": ["lightning"]})
            assert only.status_code == 422
    finally:
        tk_lightning.set_wallet(None)


async def test_failed_forward_retries_then_flags(session, dev_user):
    from app.services import dev_lightning, tk_lightning
    from xp_core.models.entities import PaymentRequest

    class Broken:
        async def forward(self, *a):
            raise RuntimeError("no route")

    tk_lightning.set_wallet(Broken())
    try:
        r = PaymentRequest(id="fwd1", user_id=dev_user.id, network=NET, username="x", address="tb1x", signature="s",
                           identity_pubkey="02", amount_sats=1000, paid_sats=1000, status="paid", paid_via="lightning",
                           ln_destination="sprt1x", forward_status="pending")
        session.add(r)
        await session.commit()
        s = Settings(_env_file=None)
        for _ in range(dev_lightning.MAX_FORWARD_ATTEMPTS):
            await dev_lightning.forward_pending(session, s)
        await session.refresh(r)
        assert r.forward_status == "failed" and "no route" in r.forward_error
    finally:
        tk_lightning.set_wallet(None)
