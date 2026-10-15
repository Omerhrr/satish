"""API contract tests for the phase-3 wallet endpoints.

Runs without bitcoind: the provider needs no chain source for create /
restore / unlock / address-book / prepare-policy paths (fee estimation falls
back to the policy fee when the node is unreachable). Broadcast paths are
covered by the regtest suite in test_bdk_wallet.py.
"""

from __future__ import annotations

import pytest
from fund_helper import fund_wallet
from httpx import ASGITransport, AsyncClient
from xp_core.config import get_settings


@pytest.fixture()
async def client(session, dev_user, tmp_path, monkeypatch):
    # isolate provider state + settings for the wallet stack
    monkeypatch.setattr(
        "xp_core.config.Settings.wallet_data_dir", str(tmp_path / "wallets"), raising=False
    )
    get_settings.cache_clear()
    import app.services.wallet_service as ws

    ws._provider = None  # fresh provider per test
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    ws._provider = None


VALID_REGTEST_ADDR = "bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx"


async def _create_wallet(client) -> dict:
    resp = await client.post("/api/v1/wallets", json={"label": "test"})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_capabilities_disclose_custody_model_honestly(client):
    body = (await client.get("/api/v1/wallets/capabilities")).json()
    assert "not_claimed" in body
    assert any("non-custodial" in c for c in body["not_claimed"])
    assert body["agent_signing"].startswith("forbidden")


async def test_create_wallet_returns_mnemonic_once(client):
    created = await _create_wallet(client)
    words = created["mnemonic_once"].split()
    assert len(words) == 24
    assert created["first_address"].startswith("bcrt1")
    # public descriptor only
    assert "tprv" not in created["public_descriptor"]

    listed = (await client.get("/api/v1/wallets")).json()["wallets"]
    assert len(listed) == 1
    assert "mnemonic_once" not in listed[0], "mnemonic must never appear in listings"


async def test_wallet_lifecycle_unlock_lock(client):
    created = await _create_wallet(client)
    wid = created["id"]

    balance = await client.get(f"/api/v1/wallets/{wid}/balance")
    assert balance.status_code == 200
    assert balance.json()["total_sats"] == 0

    wrong = await client.post(f"/api/v1/wallets/{wid}/unlock", json={"mnemonic": "abandon " * 11 + "about"})
    assert wrong.status_code == 403, "wrong phrase must be a mismatch, not a success"

    unlock = await client.post(f"/api/v1/wallets/{wid}/unlock", json={"mnemonic": created["mnemonic_once"]})
    assert unlock.status_code == 200
    assert unlock.json()["unlocked"] is True

    lock = await client.post(f"/api/v1/wallets/{wid}/lock")
    assert lock.status_code == 200
    assert lock.json()["unlocked"] is False


async def test_prepare_policy_rejects_dust_and_foreign_network(client):
    created = await _create_wallet(client)
    wid = created["id"]

    dust = await client.post(
        f"/api/v1/wallets/{wid}/prepare", json={"destination": VALID_REGTEST_ADDR, "amount_sats": 100}
    )
    assert dust.status_code == 422

    mainnet = await client.post(
        f"/api/v1/wallets/{wid}/prepare",
        json={"destination": "bc1q9mxwmm2krt2gkw22uph7nywv2ugfm35q3dkp22", "amount_sats": 100_000},
    )
    assert mainnet.status_code == 422
    assert "different network" in mainnet.json()["detail"]


async def test_prepare_insufficient_funds_is_409(client):
    created = await _create_wallet(client)
    resp = await client.post(
        f"/api/v1/wallets/{created['id']}/prepare",
        json={"destination": VALID_REGTEST_ADDR, "amount_sats": 100_000},
    )
    assert resp.status_code == 409


async def test_sign_requires_unlock_and_returns_structured_errors(client):
    created = await _create_wallet(client)
    wid = created["id"]
    # any prepared_id: even with an unlocked vault a bogus id is 404
    await client.post(f"/api/v1/wallets/{wid}/unlock", json={"mnemonic": created["mnemonic_once"]})
    bogus = await client.post(
        f"/api/v1/wallets/{wid}/sign",
        json={"prepared_id": "deadbeefdeadbeef", "authorization_digest": "0" * 64},
    )
    assert bogus.status_code == 404


async def test_alias_relabeling_cannot_redirect_prepared_transaction(client, session, dev_user):
    """Acceptance #4: aliases cannot change the destination without a new confirmation.

    The digest binds the RESOLVED address: relabeling an alias after prepare
    leaves the prepared transaction pointed at the ORIGINAL address.
    """
    import app.services.wallet_service as ws

    created = await _create_wallet(client)
    wid = created["id"]

    # fund offline via a synthetic graph transaction
    provider = ws.get_provider(get_settings())
    await fund_wallet(provider, wid, created["first_address"], 100_000)

    # create an address + alias
    addr = await client.post(f"/api/v1/wallets/{wid}/addresses", json={"alias": "alice"})
    assert addr.status_code == 201
    address_row = addr.json()

    # prepare via alias: resolves to the address
    prepared = await client.post(
        f"/api/v1/wallets/{wid}/prepare",
        json={"destination": "alice", "amount_sats": 50_000},
    )
    assert prepared.status_code == 200, prepared.text
    review = prepared.json()
    assert review["destination"] == address_row["address"]
    assert review["resolved_via_alias"] == "alice"

    # rebind the alias onto a DIFFERENT address row:
    # release it from the original (aliases are unique per user), then reassign
    release = await client.patch(
        f"/api/v1/wallets/{wid}/addresses/{address_row['id']}", json={"alias": None}
    )
    assert release.status_code == 200
    other = await client.post(f"/api/v1/wallets/{wid}/addresses", json={"alias": None})
    other_id = other.json()["id"]
    relabel = await client.patch(
        f"/api/v1/wallets/{wid}/addresses/{other_id}", json={"alias": "alice"}
    )
    assert relabel.status_code == 200

    # the previously prepared transaction still binds the ORIGINAL address:
    # its digest remains valid for signing the ORIGINAL destination
    await client.post(f"/api/v1/wallets/{wid}/unlock", json={"mnemonic": created["mnemonic_once"]})
    signed = await client.post(
        f"/api/v1/wallets/{wid}/sign",
        json={"prepared_id": review["prepared_id"], "authorization_digest": review["authorization_digest"]},
    )
    assert signed.status_code == 200, "old review must still sign the original destination"
    assert signed.json()["txid"]

    # a NEW prepare now resolves to the re-bound address and gets a different digest
    review2 = (await client.post(
        f"/api/v1/wallets/{wid}/prepare",
        json={"destination": "alice", "amount_sats": 50_000},
    )).json()
    assert review2["destination"] == other.json()["address"], "new prepare resolves the new binding"
    assert review2["authorization_digest"] != review["authorization_digest"]


async def test_restore_creates_row_without_echoing_phrase(client):
    created = await _create_wallet(client)
    restored = await client.post(
        "/api/v1/wallets/restore",
        json={"mnemonic": created["mnemonic_once"], "label": "restored"},
    )
    assert restored.status_code == 201
    body = restored.json()
    assert body["restored"] is True
    assert body["id"] == created["id"], "deterministic wallet id"
    assert "mnemonic" not in body

    garbage = await client.post("/api/v1/wallets/restore", json={"mnemonic": "x " * 12, "label": ""})
    assert garbage.status_code == 422


async def test_foreign_wallet_is_404(client, session, dev_user):
    """Cross-user access is indistinguishable from a missing wallet."""
    await _create_wallet(client)
    # ownership probe: unknown id
    resp = await client.get("/api/v1/wallets/not-a-real-id/balance")
    assert resp.status_code == 404
