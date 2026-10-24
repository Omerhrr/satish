"""TK economy v2: welcome TK, buy by TK amount (5 TK/sat, min 500 TK),
pay by Bitcoin or Lightning into the operator's wallet, automatic charging."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import PaymentIntent, XpLedgerEntry
from xp_core.services import ledger

from app.services import tk_lightning
from tests.test_agent_runtime import client  # noqa: F401  (fixture)
from tests.test_telegram_auth import BOT_TOKEN, make_init_data


class FakePayee:
    def __init__(self):
        self.made: list[str] = []
        self.paid: set[str] = set()

    async def create_invoice(self, amount_sats, description, expiry_secs):
        inv = f"lnbcrt{amount_sats}n1fake{len(self.made)}"
        self.made.append(inv)
        return inv

    async def paid_invoices(self, since_unix):
        return {i.lower() for i in self.paid}


@pytest.fixture()
def payee():
    w = FakePayee()
    tk_lightning.set_wallet(w)
    yield w
    tk_lightning.set_wallet(None)


async def test_every_account_gets_welcome_tk_once(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", BOT_TOKEN)
    init = make_init_data('{"id": 5551, "username": "ada"}')
    first = await client.post("/api/v1/auth/telegram", json={"init_data": init})
    assert first.status_code == 200, first.text
    headers = {"Authorization": f"Bearer {first.json()['session_token']}"}
    assert (await client.get("/api/v1/xp/balance", headers=headers)).json()["balance_xp"] == s.tk_welcome_bonus
    await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data('{"id": 5551, "username": "ada"}')})
    assert (await client.get("/api/v1/xp/balance", headers=headers)).json()["balance_xp"] == s.tk_welcome_bonus


async def test_buy_by_tk_amount_with_minimum(client, payee):
    s = get_settings()
    assert s.xp_per_sat == 5
    low = await client.post("/api/v1/xp/purchases", json={"tk_amount": 499, "method": "lightning"})
    assert low.status_code == 422 and "500" in low.json()["detail"]
    ok = await client.post("/api/v1/xp/purchases", json={"tk_amount": 500, "method": "lightning"})
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["amount_sats"] == 100 and body["xp_amount"] == 500
    assert body["bolt11"] == payee.made[0] and body["payment_method"] == "lightning"
    odd = (await client.post("/api/v1/xp/purchases", json={"tk_amount": 503, "method": "lightning"})).json()
    assert odd["amount_sats"] == 101 and odd["xp_amount"] == 505  # rounds up, never under-charges


async def test_lightning_purchase_credits_once_when_paid(client, session, dev_user, payee):
    body = (await client.post("/api/v1/xp/purchases", json={"tk_amount": 1000, "method": "lightning"})).json()
    pending = (await client.get(f"/api/v1/xp/purchases/{body['id']}")).json()
    assert pending["status"] == "pending"
    payee.paid.add(body["bolt11"])
    done = (await client.get(f"/api/v1/xp/purchases/{body['id']}")).json()
    assert done["status"] == "settled"
    again = await tk_lightning.sweep(session, get_settings())
    assert again["settled"] == 0
    credits = (
        await session.execute(select(XpLedgerEntry).where(XpLedgerEntry.entry_type == "purchase"))
    ).scalars().all()
    assert [c.amount for c in credits] == [1000]


async def test_rate_lists_methods_and_payee(client, payee, monkeypatch):
    monkeypatch.setattr(get_settings(), "tk_payee_username", "@satish")
    r = (await client.get("/api/v1/xp/rate")).json()
    assert r["xp_per_sat"] == 5 and r["min_tk"] == 500 and r["payee_username"] == "satish"
    assert "lightning" in r["methods"]


async def test_task_without_budget_uses_balance_automatically(client, session, dev_user):
    await ledger.grant_welcome(session, user_id=dev_user.id, amount=300)
    await session.commit()
    t = (await client.post("/api/v1/tasks", json={"objective": "hello"})).json()
    assert t["budget_xp"] == 300  # capped by the balance, not a number the user typed


async def test_task_without_tk_is_refused_kindly(client):
    r = await client.post("/api/v1/tasks", json={"objective": "hello"})
    assert r.status_code == 402 and "Buy more TK" in r.json()["detail"]


async def test_own_satish_wallet_receives_bitcoin_tk_at_5000_plus(client, monkeypatch):
    from xp_core.services.onchain import TK_START, derive_address, xpub_from_mnemonic

    s = get_settings()
    words = "abandon " * 11 + "about"
    monkeypatch.setattr(s, "tk_wallet_mnemonic", words)
    monkeypatch.setattr(s, "onchain_network", "testnet")
    r = (await client.get("/api/v1/xp/rate")).json()
    assert "onchain" in r["methods"] and "lightning" in r["methods"]  # one phrase sets up both
    a = (await client.post("/api/v1/xp/purchases", json={"tk_amount": 500, "method": "onchain"})).json()
    b = (await client.post("/api/v1/xp/purchases", json={"tk_amount": 500, "method": "onchain"})).json()
    xpub = xpub_from_mnemonic(words, "testnet")
    assert a["address"] == derive_address(xpub, "testnet", TK_START)
    assert b["address"] == derive_address(xpub, "testnet", TK_START + 1)


async def test_old_unpaid_address_is_reused(client, session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from xp_core.services import onchain

    s = get_settings()
    monkeypatch.setattr(s, "tk_wallet_mnemonic", "abandon " * 11 + "about")
    first = (await client.post("/api/v1/xp/purchases", json={"tk_amount": 500, "method": "onchain"})).json()
    row = await session.get(PaymentIntent, first["id"])
    row.status = "expired"
    row.expires_at = datetime.now(UTC) - timedelta(days=2)
    await session.commit()

    async def nothing(client, base, address, min_conf):
        return onchain.PaymentCheck(address=address)

    monkeypatch.setattr(onchain, "check_address", nothing)
    again = (await client.post("/api/v1/xp/purchases", json={"tk_amount": 500, "method": "onchain"})).json()
    assert again["address"] == first["address"]
    await session.refresh(row)
    assert row.provider_reference.startswith("released:")
