"""@usernames + signed address pools + shareable payment requests."""

from __future__ import annotations

import httpx
import pytest
from embit import bip32, bip39, script
from embit.networks import NETWORKS
from sqlalchemy import select
from xp_core.config import Settings
from xp_core.models.entities import (
    HandleAddress,
    Notification,
    PaymentRequest,
    User,
    WalletHandle,
)
from xp_core.services import handles as svc
from xp_core.services.relay import render_notification_text

NET = "testnet"


def wallet(words: str):
    root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed(words))
    acct = root.derive("m/84h/1h/0h")
    identity = acct.derive([7, 0]).key  # private key on the identity chain

    def signed(i: int) -> svc.SignedAddress:
        addr = script.p2wpkh(acct.derive([0, i]).to_public()).address(NETWORKS["test"])
        sig = identity.sign(svc.address_message(NET, addr)).serialize().hex()
        return svc.SignedAddress(address=addr, index=i, signature=sig)

    return identity.get_public_key().sec().hex(), signed


ADA = wallet("abandon " * 11 + "about")
BOB = wallet("legal winner thank year wave sausage worth useful legal winner thank yellow")


async def _user(session, name: str) -> User:
    u = User(display_name=name)
    session.add(u)
    await session.flush()
    return u


def test_signature_check():
    pub, signed = ADA
    s = signed(1000)
    assert svc.verify_address_signature(pub, NET, s.address, s.signature)
    assert not svc.verify_address_signature(pub, "mainnet", s.address, s.signature)  # bound to network
    assert not svc.verify_address_signature(BOB[0], NET, s.address, s.signature)
    assert not svc.verify_address_signature(pub, NET, s.address, "zz")
    assert svc.username_problem("ab") and svc.username_problem("Ada!") and svc.username_problem("admin")
    assert svc.normalize_username(" @Ada_1 ") == "ada_1" and not svc.username_problem("ada_1")


async def test_claim_rules_and_pool(session):
    ada, bob = await _user(session, "Ada"), await _user(session, "Bob")
    pub, signed = ADA
    h = await svc.claim(session, ada, network=NET, username="@Ada", identity_pubkey=pub, addresses=[signed(i) for i in range(1000, 1005)])
    assert h.username == "ada"
    assert await svc.pool_status(session, ada, NET) == {"available": 5, "max_index": 1004, "issued_max_index": -1}
    with pytest.raises(svc.HandleError, match="taken"):
        await svc.claim(session, bob, network=NET, username="ada", identity_pubkey=BOB[0], addresses=[])
    # forged signature: rejected, nothing stored
    bad = signed(1010)
    bad.signature = BOB[1](1010).signature
    with pytest.raises(svc.HandleError, match="signature"):
        await svc.add_addresses(session, ada, NET, pub, [bad])
    # mainnet address on testnet
    main = script.p2wpkh(bip32.HDKey.from_seed(bip39.mnemonic_to_seed("abandon " * 11 + "about")).derive("m/84h/0h/0h/0/0").to_public()).address()
    with pytest.raises(svc.HandleError, match="valid"):
        await svc.add_addresses(session, ada, NET, pub, [svc.SignedAddress(main, 1, signed(1).signature)])

    # fresh address per payment, in order, then reuse when empty
    issued = [(await svc.issue_address(session, h)) for _ in range(5)]
    assert [a.derivation_index for a, _ in issued] == [1000, 1001, 1002, 1003, 1004]
    assert not any(r for _, r in issued)
    again, reused = await svc.issue_address(session, h)
    assert reused and again.address == issued[-1][0].address

    # rename: old name held for others
    await svc.claim(session, ada, network=NET, username="ada_k", identity_pubkey=pub, addresses=[])
    assert "recently" in await svc.name_availability(session, NET, "ada", bob)
    assert await svc.name_availability(session, NET, "ada", ada) == ""  # owner can take it back


async def test_new_wallet_drops_old_unissued_addresses(session):
    ada = await _user(session, "Ada")
    await svc.claim(session, ada, network=NET, username="ada", identity_pubkey=ADA[0], addresses=[ADA[1](i) for i in range(3)])
    await svc.claim(session, ada, network=NET, username="ada", identity_pubkey=BOB[0], addresses=[BOB[1](0)])
    rows = (await session.execute(select(HandleAddress).where(HandleAddress.status == "available"))).scalars().all()
    assert [r.identity_pubkey for r in rows] == [BOB[0]]


class Chain:
    def __init__(self):
        self.paid: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/api", 1)[1]
        if path == "/blocks/tip/height":
            return httpx.Response(200, text="100")
        addr = path.split("/")[2]
        v = self.paid.get(addr, 0)
        txs = [{"txid": "ab" * 32, "status": {"confirmed": False}, "vout": [{"scriptpubkey_address": addr, "value": v}]}] if v else []
        return httpx.Response(200, json=txs)


async def test_request_lifecycle_and_api(session, dev_user, monkeypatch):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    chain = Chain()
    real = httpx.AsyncClient
    monkeypatch.setattr(svc.httpx, "AsyncClient", lambda **kw: real(**({"transport": httpx.MockTransport(chain.handler)} | kw)))
    import app.api.v1.handles as api_mod

    monkeypatch.setattr(api_mod, "get_settings", lambda: Settings(_env_file=None, onchain_min_conf=0, mini_app_url="https://satish.rogan.live"))

    pub, signed = ADA
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/handles/check", params={"username": "ada", "network": NET})
        assert r.json()["available"] is True
        r = await c.post("/api/v1/requests", json={"network": NET, "amount_sats": 5000})
        assert r.status_code == 422 and "username" in r.json()["detail"]
        body = {"network": NET, "username": "ada", "identity_pubkey": pub,
                "addresses": [{"address": s.address, "index": s.index, "signature": s.signature} for s in map(signed, range(1000, 1010))]}
        r = await c.post("/api/v1/handles/claim", json=body)
        assert r.status_code == 200 and r.json()["available"] == 10

        r = await c.post("/api/v1/handles/ada/address", params={"network": NET})
        sent_to = r.json()
        assert sent_to["address"] == signed(1000).address
        assert svc.verify_address_signature(sent_to["identity_pubkey"], NET, sent_to["address"], sent_to["signature"])
        assert (await c.post("/api/v1/handles/nobody/address", params={"network": NET})).status_code == 404

        r = await c.post("/api/v1/requests", json={"network": NET, "amount_sats": 5000, "note": "rice"})
        req = r.json()
        assert r.status_code == 201 and req["url"] == f"https://satish.rogan.live/pay/{req['id']}"
        assert req["address"] == signed(1001).address and req["username"] == "ada"

        # public, no auth needed; partial then full payment
        chain.paid[req["address"]] = 2000
        r = await c.get(f"/api/v1/requests/{req['id']}")
        assert r.json()["status"] == "open" and r.json()["paid_sats"] == 2000
        chain.paid[req["address"]] = 5000
        row = await session.get(PaymentRequest, req["id"])
        row.checked_at = None
        await session.commit()
        r = await c.get(f"/api/v1/requests/{req['id']}")
        assert r.json()["status"] == "paid"

        n = (await session.execute(select(Notification).where(Notification.kind == "request.paid"))).scalars().all()
        assert len(n) == 1 and "5,000 sats" in render_notification_text(n[0], None) and "rice" in render_notification_text(n[0], None)

        r = await c.get(f"/api/v1/requests/{req['id']}")  # seen again: still one notification
        assert len((await session.execute(select(Notification))).scalars().all()) == 1
        assert (await c.get("/api/v1/requests/doesnotexist")).status_code == 404


async def test_closure_erases_usernames(session, dev_user):
    await svc.claim(session, dev_user, network=NET, username="closer", identity_pubkey=ADA[0], addresses=[ADA[1](0)])
    await svc.create_request(session, dev_user, network=NET, amount_sats=1000, note=None)
    await session.commit()
    from xp_core.config import get_settings
    from xp_core.services.closure import close_account

    await close_account(session, dev_user, get_settings())
    for model in (WalletHandle, HandleAddress, PaymentRequest):
        assert (await session.execute(select(model))).scalars().all() == []


SPARK = "sprt1pgssyuuuhnrrdjswal5c3s3rafw9w3y5dd4cjy3duxlf7hjzkp0rqx6dj6mrhu"


def _spark_sig(words_wallet, ln_net: str, addr: str) -> str:
    root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed(words_wallet))
    identity = root.derive("m/84h/1h/0h").derive([7, 0]).key
    return identity.sign(svc.spark_message(NET, ln_net, addr)).serialize().hex()


async def test_username_lightning_address(session, dev_user):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    pub, signed = ADA
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        body = {"network": NET, "identity_pubkey": pub, "ln_network": "regtest", "spark_address": SPARK,
                "signature": _spark_sig("abandon " * 11 + "about", "regtest", SPARK)}
        r = await c.post("/api/v1/handles/lightning", json=body)
        assert r.status_code == 422 and "username" in r.json()["detail"]  # needs a username first

        claim = {"network": NET, "username": "ada", "identity_pubkey": pub,
                 "addresses": [{"address": s.address, "index": s.index, "signature": s.signature} for s in map(signed, range(1000, 1003))]}
        assert (await c.post("/api/v1/handles/claim", json=claim)).status_code == 200

        r = await c.get("/api/v1/handles/ada/lightning", params={"network": NET})
        assert r.status_code == 404 and "hasn't opened Lightning" in r.json()["detail"]

        # forged: signed by Bob's key / for a different address / wrong owner key
        bad = body | {"signature": _spark_sig("legal winner thank year wave sausage worth useful legal winner thank yellow", "regtest", SPARK)}
        assert (await c.post("/api/v1/handles/lightning", json=bad)).status_code == 422
        other = body | {"spark_address": SPARK[:-4] + "qqqq"}
        assert (await c.post("/api/v1/handles/lightning", json=other)).status_code == 422
        assert (await c.post("/api/v1/handles/lightning", json=body | {"identity_pubkey": BOB[0]})).status_code == 422
        assert (await c.post("/api/v1/handles/lightning", json=body | {"spark_address": "not an address at all!!"})).status_code == 422

        r = await c.post("/api/v1/handles/lightning", json=body)
        assert r.status_code == 200
        r = await c.get("/api/v1/handles/@Ada/lightning", params={"network": NET})
        got = r.json()
        assert got["spark_address"] == SPARK and got["ln_network"] == "regtest"
        assert svc.verify_spark_signature(got["identity_pubkey"], NET, got["ln_network"], got["spark_address"], got["signature"])
        assert not svc.verify_spark_signature(got["identity_pubkey"], NET, "mainnet", got["spark_address"], got["signature"])
        assert (await c.get("/api/v1/handles/nobody/lightning", params={"network": NET})).status_code == 404


async def test_lightning_status_in_me_and_address_normalised(session, dev_user):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    pub, signed = ADA
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        claim = {"network": NET, "username": "ada", "identity_pubkey": pub,
                 "addresses": [{"address": s.address, "index": s.index, "signature": s.signature} for s in map(signed, range(1000, 1002))]}
        assert (await c.post("/api/v1/handles/claim", json=claim)).status_code == 200
        me = (await c.get("/api/v1/handles/me", params={"network": NET})).json()
        assert me["lightning_address"] is None
        real = "sparkrt1pgssyuuuhnrrdjswal5c3s3rafw9w3y5dd4cjy3duxlf7hjzkp0rqx6dj6mrhu"  # documented regtest format
        body = {"network": NET, "identity_pubkey": pub, "ln_network": "regtest",
                "spark_address": "spark:" + real.upper(), "signature": _spark_sig("abandon " * 11 + "about", "regtest", real)}
        r = await c.post("/api/v1/handles/lightning", json=body)
        assert r.status_code == 200 and r.json()["spark_address"] == real
        me = (await c.get("/api/v1/handles/me", params={"network": NET})).json()
        assert me["lightning_address"] == real and me["lightning_network"] == "regtest"


from tests.test_agent_runtime import client  # noqa: E402,F401


async def test_current_names_follow_renames(client, session, dev_user):
    from xp_core.models.entities import WalletHandle

    session.add(WalletHandle(user_id=dev_user.id, network="testnet", username="ada_new", identity_pubkey="02" + "b" * 64))
    session.add(WalletHandle(user_id=dev_user.id, network="testnet", username="ada_old", identity_pubkey="02" + "b" * 64, status="released"))
    await session.commit()
    r = await client.post("/api/v1/handles/current-names", json={"network": "testnet", "identity_pubkeys": ["02" + "B" * 64, "02" + "c" * 64]})
    assert r.status_code == 200 and r.json() == {"02" + "b" * 64: "ada_new"}
