"""On-chain XP payments: watch-only addresses, confirmation policy, exactly-once credit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from embit import bip32, bip39
from embit.networks import NETWORKS
from sqlalchemy import select
from xp_core.config import Settings
from xp_core.models.entities import PaymentIntent, XpAccount, XpLedgerEntry
from xp_core.services import onchain

SEED = bip39.mnemonic_to_seed("abandon " * 11 + "about")
TPUB = bip32.HDKey.from_seed(SEED).derive("m/84h/1h/0h").to_public().to_base58(version=NETWORKS["test"]["xpub"])
XPUB = bip32.HDKey.from_seed(SEED).derive("m/84h/0h/0h").to_public().to_base58()


class FakeChain:
    """Esplora stand-in: tip height + per-address transactions."""

    def __init__(self) -> None:
        self.tip = 1000
        self.txs: dict[str, list[dict]] = {}

    def pay(self, address: str, sats: int, *, height: int | None = None, txid: str = "aa") -> None:
        status = {"confirmed": height is not None, "block_height": height}
        self.txs.setdefault(address, []).append(
            {"txid": txid * 32, "status": status, "vout": [{"scriptpubkey_address": address, "value": sats}]}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/api", 1)[1]
        if path == "/blocks/tip/height":
            return httpx.Response(200, text=str(self.tip))
        if path.startswith("/address/") and path.endswith("/txs"):
            return httpx.Response(200, json=self.txs.get(path.split("/")[2], []))
        return httpx.Response(404)


@pytest.fixture()
def chain(monkeypatch):
    c = FakeChain()
    real = httpx.AsyncClient
    monkeypatch.setattr(onchain.httpx, "AsyncClient", lambda **kw: real(**({"transport": httpx.MockTransport(c.handler)} | kw)))
    return c


def _s(**kw) -> Settings:
    base = {"payment_mode": "onchain", "onchain_xpub": TPUB, "onchain_network": "testnet", "onchain_min_conf": 1}
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_derivation_matches_bip84_vectors_and_rejects_private_keys():
    assert onchain.derive_address(TPUB, "testnet", 0) == "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl"
    assert onchain.derive_address(XPUB, "mainnet", 0) == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    assert onchain.derive_address(XPUB, "mainnet", 1) == "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
    xprv = bip32.HDKey.from_seed(SEED).derive("m/84h/1h/0h").to_base58(version=NETWORKS["test"]["xprv"])
    with pytest.raises(onchain.OnchainConfigError):
        onchain.derive_address(xprv, "testnet", 0)
    with pytest.raises(onchain.OnchainConfigError):
        onchain.derive_address("not-a-key", "testnet", 0)
    assert onchain.bip21("tb1qx", 150_000) == "bitcoin:tb1qx?amount=0.0015&label=XP%20credits"


async def _balance(session, user_id):
    acct = (await session.execute(select(XpAccount).where(XpAccount.user_id == user_id))).scalar_one_or_none()
    return acct.balance if acct else 0


async def test_unique_addresses_and_confirmation_policy_and_exactly_once(session, dev_user, chain):
    s = _s()
    a = await onchain.create_intent(session, user=dev_user, settings=s, amount_sats=1000)
    b = await onchain.create_intent(session, user=dev_user, settings=s, amount_sats=5000)
    await session.commit()
    assert onchain.intent_address(a) != onchain.intent_address(b)
    assert a.bolt11.startswith("bitcoin:tb1q") and a.xp_amount == 1000 * s.xp_per_sat

    addr = onchain.intent_address(a)
    chain.pay(addr, 400, height=990, txid="01")  # underpaid
    await onchain.settle_if_paid(session, a, s)
    assert a.status == "pending" and await _balance(session, dev_user.id) == 0

    chain.pay(addr, 600, txid="02")  # tops up, but unconfirmed
    check = await onchain.settle_if_paid(session, a, s)
    assert a.status == "pending" and check.seen_sats == 1000 and check.counted_sats == 400

    chain.txs[addr][1]["status"] = {"confirmed": True, "block_height": 1000}
    await onchain.settle_if_paid(session, a, s)
    assert a.status == "settled" and await _balance(session, dev_user.id) == a.xp_amount

    # seen again (worker + app both checking): no second credit
    await onchain.settle_if_paid(session, a, s)
    a.status = "pending"  # even a forced re-check can't double-credit
    await onchain.settle_if_paid(session, a, s)
    entries = (await session.execute(select(XpLedgerEntry).where(XpLedgerEntry.reference_id == a.id))).scalars().all()
    assert len(entries) == 1 and await _balance(session, dev_user.id) == a.xp_amount


async def test_zero_conf_and_late_payment_after_expiry(session, dev_user, chain):
    s = _s(onchain_min_conf=0)
    a = await onchain.create_intent(session, user=dev_user, settings=s, amount_sats=2000)
    a.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()
    await onchain.settle_if_paid(session, a, s)
    assert a.status == "expired"
    chain.pay(onchain.intent_address(a), 2000)  # arrives late, unconfirmed, 0-conf allowed
    result = await onchain.sweep(session, s)
    await session.refresh(a)
    assert a.status == "settled" and result["settled"] == 1
    assert await _balance(session, dev_user.id) == 2000 * s.xp_per_sat


async def test_api_flow(session, dev_user, chain, monkeypatch):
    import app.api.v1.xp as xp_api
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(xp_api, "get_settings", lambda: _s(onchain_min_conf=0))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/xp/purchases", json={"pack_id": "pack_1000sats"})
        assert r.status_code == 201, r.text
        p = r.json()
        assert p["payment_method"] == "onchain" and p["network"] == "testnet" and p["address"].startswith("tb1q")
        r = await c.get(f"/api/v1/xp/purchases/{p['id']}")
        assert r.json()["status"] == "pending" and r.json()["seen_sats"] == 0
        chain.pay(p["address"], 1000)
        r = await c.get(f"/api/v1/xp/purchases/{p['id']}")
        assert r.json()["status"] == "settled" and r.json()["balance_after"] == p["xp_amount"]

    monkeypatch.setattr(xp_api, "get_settings", lambda: _s(onchain_xpub=None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/xp/purchases", json={"pack_id": "pack_1000sats"})
        assert r.status_code == 503
    rows = (await session.execute(select(PaymentIntent))).scalars().all()
    assert all(r.provider_reference.startswith("onchain:") for r in rows)
