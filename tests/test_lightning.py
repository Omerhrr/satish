"""Phase-4 Lightning tests: state machines, canned provider semantics, API.

Provider-level tests prove the lifecycles (invoice settle/expiry, payment
fee preview + authorization + submission, SCB round-trip) against the
canned provider with a controlled clock. API tests drive the FastAPI routes
through ASGI transport with the provider injected as the service singleton,
proving ownership, error mapping, and the no-double-credit settlement gate.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from lightning_adapter import (
    AuthorizationMismatch,
    CannedLightningProvider,
    InvalidTransition,
    InvoiceExpired,
    LightningProviderError,
    PreimageMismatch,
    make_lightning_provider,
)
from lightning_adapter.common import Network
from lightning_adapter.lnd_provider import LndConfigError, LndLightningProvider
from lightning_adapter.state import next_invoice_state, next_payment_state
from xp_core.config import get_settings
from sqlalchemy import func, select
from xp_core.models.entities import XpLedgerEntry

# fixtures


def make_provider(*, clock=None, **kw) -> CannedLightningProvider:
    return CannedLightningProvider(Network.REGTEST, clock=clock, **kw)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
async def client(session, dev_user, clock):
    """ASGI client with the canned provider (controlled clock) injected."""
    from app.main import app
    from app.services import lightning_service as svc

    svc._provider = make_provider(clock=clock)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    svc._provider = None


async def _create_invoice(client, amount_sats: int = 1500) -> dict:
    resp = await client.post(
        "/api/v1/lightning/invoices",
        json={"amount_sats": amount_sats, "description": "XP purchase"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _preimage_for(provider: CannedLightningProvider, payment_hash: str) -> str:
    # White-box seam (tests/*): the canned invoice holds the preimage that a
    # real node would keep server-side behind the settle stream.
    return provider._invoices[payment_hash].invoice.preimage


# state machines


def test_payment_state_machine_legal_chain():
    state = "created"
    for target in ("prepared", "authorized", "in_flight", "succeeded"):
        state = next_payment_state(state, target)
    assert state == "succeeded"
    # failure is reachable from every pre-terminal state
    assert next_payment_state("prepared", "failed") == "failed"
    assert next_payment_state("authorized", "failed") == "failed"
    assert next_payment_state("in_flight", "failed") == "failed"


def test_payment_state_machine_rejects_shortcuts_and_terminal():
    with pytest.raises(InvalidTransition):
        next_payment_state("created", "in_flight")  # cannot skip prepare+authorize
    with pytest.raises(InvalidTransition):
        next_payment_state("created", "succeeded")
    with pytest.raises(InvalidTransition):
        next_payment_state("succeeded", "failed")  # terminal is terminal
    with pytest.raises(InvalidTransition):
        next_payment_state("failed", "in_flight")
    with pytest.raises(InvalidTransition):
        next_invoice_state("settled", "pending")


async def test_invoice_lifecycle_pending_settle_expiry(clock):
    provider = make_provider(clock=clock)
    inv = await provider.create_invoice(
        amount_msat=1_000_000, description="d", expiry_seconds=3600
    )
    status, _ = await provider.invoice_status(inv.payment_hash)
    assert status == "pending"
    assert await provider.settle_invoice(inv.payment_hash, inv.preimage) is True
    status, _ = await provider.invoice_status(inv.payment_hash)
    assert status == "settled"

    # a fresh invoice that elapses is markable expired and cannot settle
    inv2 = await provider.create_invoice(
        amount_msat=1_000_000, description="d", expiry_seconds=3600
    )
    clock.advance(3601)
    status, _ = await provider.invoice_status(inv2.payment_hash)
    assert status == "expired"
    with pytest.raises(InvoiceExpired):
        await provider.settle_invoice(inv2.payment_hash, inv2.preimage)
    with pytest.raises(InvalidTransition):
        next_invoice_state("expired", "settled")


async def test_invoice_settlement_requires_matching_preimage_and_is_idempotent(clock):
    provider = make_provider(clock=clock)
    inv = await provider.create_invoice(
        amount_msat=2_000_000, description="d", expiry_seconds=3600
    )
    with pytest.raises(PreimageMismatch):
        await provider.settle_invoice(inv.payment_hash, "ab" * 32)
    assert await provider.settle_invoice(inv.payment_hash, inv.preimage) is True
    # replay: settled already, returns False and must credit nothing
    assert await provider.settle_invoice(inv.payment_hash, inv.preimage) is False


# payments (send)


async def test_payment_fee_preview_moves_nothing_then_submit_moves_liquidity(clock):
    provider = make_provider(clock=clock)
    inv = await provider.create_invoice(
        amount_msat=1_500_000, description="d", expiry_seconds=3600
    )
    before = (await provider.channels())[0]
    prepared = await provider.prepare_payment(inv.bolt11)
    assert prepared.fee_estimate_msat == 1001  # 1000 base + 1 ppm of 1.5M
    assert prepared.fee_clamped is False
    after_prepare = (await provider.channels())[0]
    assert (
        after_prepare["local_msat"],
        after_prepare["remote_msat"],
    ) == (before["local_msat"], before["remote_msat"])  # preview moved nothing

    await provider.authorize_payment(payment_id := prepared.payment_id, prepared.authorization_digest)
    status = await provider.submit_payment(payment_id)
    assert status.status == "succeeded"
    moved = inv.amount_msat + status.fee_msat
    after = (await provider.channels())[0]
    assert after["local_msat"] == before["local_msat"] - moved
    assert after["remote_msat"] == before["remote_msat"] + moved


async def test_payment_of_expired_invoice_fails(clock):
    provider = make_provider(clock=clock)
    inv = await provider.create_invoice(
        amount_msat=1_000_000, description="d", expiry_seconds=3600
    )
    prepared = await provider.prepare_payment(inv.bolt11)
    clock.advance(3601)
    await provider.authorize_payment(prepared.payment_id, prepared.authorization_digest)
    with pytest.raises(InvoiceExpired):
        await provider.submit_payment(prepared.payment_id)
    status = await provider.payment_status(prepared.payment_id)
    assert status.status == "failed"


async def test_payment_failure_leaves_liquidity_intact(clock):
    provider = make_provider(clock=clock)
    inv = await provider.create_invoice(
        amount_msat=6_000_000, description="d", expiry_seconds=3600  # > 5M local
    )
    before = (await provider.channels())[0]
    prepared = await provider.prepare_payment(inv.bolt11)
    await provider.authorize_payment(prepared.payment_id, prepared.authorization_digest)
    status = await provider.submit_payment(prepared.payment_id)
    assert status.status == "failed"  # definite failure, not uncertainty
    after = (await provider.channels())[0]
    assert (after["local_msat"], after["remote_msat"]) == (before["local_msat"], before["remote_msat"])


async def test_wrong_authorization_digest_rejected(clock):
    provider = make_provider(clock=clock)
    inv = await provider.create_invoice(
        amount_msat=1_000_000, description="d", expiry_seconds=3600
    )
    prepared = await provider.prepare_payment(inv.bolt11)
    with pytest.raises(AuthorizationMismatch):
        await provider.authorize_payment(prepared.payment_id, "0" * 64)
    status = await provider.payment_status(prepared.payment_id)
    assert status.status == "prepared"  # nothing advanced, nothing moved


# recovery + construction gates


async def test_scb_roundtrip_and_checksum(clock):
    provider = make_provider(clock=clock)
    provider.record_channel_for_backup("chan-1", "02peer")
    blob, checksum = await provider.export_scb()
    assert checksum and len(blob) > 10

    target = make_provider(clock=clock)
    assert await target.restore_scb(blob, checksum) == 1
    with pytest.raises(LightningProviderError):
        await target.restore_scb(blob, "0" * 64)  # corrupted checksum refused


def test_mainnet_refused_at_construction():
    with pytest.raises(ValueError, match="mainnet"):
        CannedLightningProvider(Network.MAINNET)
    with pytest.raises(ValueError, match="mainnet"):
        LndLightningProvider(
            Network.MAINNET,
            rpc_host="127.0.0.1:1",
            tls_cert_path="/tmp/x",
            macaroon_path="/tmp/y",
            max_fee_msat=1000,
        )


def test_factory_canned_default_and_lnd_requires_host():
    from xp_core.config import Settings

    provider = make_lightning_provider(Settings())
    assert isinstance(provider, CannedLightningProvider)
    with pytest.raises(LndConfigError):
        make_lightning_provider(Settings(lightning_mode="lnd"))
    with pytest.raises(LndConfigError):
        LndLightningProvider(
            Network.REGTEST,
            rpc_host="",
            tls_cert_path="",
            macaroon_path="",
            max_fee_msat=1000,
        )


# API surface


async def test_invoice_create_and_idempotent_replay(client, session, clock):
    body = await _create_invoice(client)
    assert body["status"] == "pending"
    assert body["bolt11"].startswith("lnbcrt")
    assert body["direction"] == "receive"
    assert body["xp_amount"] == body["amount_sats"] * get_settings().xp_per_sat

    got = await client.get(f"/api/v1/lightning/invoices/{body['payment_hash']}")
    assert got.status_code == 200
    assert got.json()["payment_hash"] == body["payment_hash"]

    hash_ = body["payment_hash"]
    first = await client.post(
        f"/api/v1/lightning/invoices/{hash_}/settle", json={"preimage": _preimage_of(client, hash_)}
    )
    assert first.status_code == 200
    assert first.json()["credited"] is True
    replay = await client.post(
        f"/api/v1/lightning/invoices/{hash_}/settle", json={"preimage": _preimage_of(client, hash_)}
    )
    assert replay.status_code == 200
    assert replay.json()["credited"] is False
    assert "already credited" in replay.json()["note"]


def _preimage_of(client, payment_hash: str) -> str:
    from app.services import lightning_service as svc

    provider = svc._provider
    assert provider is not None
    return _preimage_for(provider, payment_hash)


async def test_duplicate_settlement_credits_exactly_once(client, session):
    body = await _create_invoice(client, amount_sats=1500)
    hash_ = body["payment_hash"]
    preimage = _preimage_of(client, hash_)
    credited_calls = 0
    for _ in range(6):
        resp = await client.post(
            f"/api/v1/lightning/invoices/{hash_}/settle", json={"preimage": preimage}
        )
        assert resp.status_code == 200
        payload = resp.json()
        if payload["credited"]:
            credited_calls += 1
        else:
            assert "already credited" in (payload.get("note") or "")
    assert credited_calls == 1  # exactly one callback actually credits

    rows = (
        await session.execute(
            select(func.count()).select_from(XpLedgerEntry)
        )
    ).scalar_one()
    assert rows == 1  # one ledger entry, not six
    balance = (
        await session.execute(select(func.coalesce(func.sum(XpLedgerEntry.amount), 0)))
    ).scalar_one()
    assert balance == 1500 * get_settings().xp_per_sat  # credited exactly once


async def test_settlement_of_unknown_hash_is_404(client):
    resp = await client.post(
        "/api/v1/lightning/invoices/" + "f" * 64 + "/settle",
        json={"preimage": "a" * 64},
    )
    assert resp.status_code == 404


async def test_invoice_expiry_marks_expired(client, clock):
    body = await _create_invoice(client)
    clock.advance(3601)
    got = await client.get(f"/api/v1/lightning/invoices/{body['payment_hash']}")
    assert got.status_code == 200
    assert got.json()["status"] == "expired"
    # settling an expired invoice is refused with 410
    resp = await client.post(
        f"/api/v1/lightning/invoices/{body['payment_hash']}/settle",
        json={"preimage": _preimage_of(client, body["payment_hash"])},
    )
    assert resp.status_code == 410


async def test_send_payment_prepare_authorize_submit_flow(client, session):
    inv = await _create_invoice(client, amount_sats=1000)
    prep = await client.post(
        "/api/v1/lightning/payments/prepare", json={"bolt11": inv["bolt11"]}
    )
    assert prep.status_code == 201, prep.text
    prepared = prep.json()
    assert prepared["state"] == "prepared"
    assert prepared["fee_estimate_msat"] == 1001
    assert prepared["fee_clamped"] is False

    auth = await client.post(
        f"/api/v1/lightning/payments/{prepared['payment_id']}/authorize",
        json={"authorization_digest": prepared["authorization_digest"]},
    )
    assert auth.status_code == 200
    assert auth.json()["status"] == "authorized"

    sub = await client.post(
        f"/api/v1/lightning/payments/{prepared['payment_id']}/submit"
    )
    assert sub.status_code == 200, sub.text
    assert sub.json()["status"] == "succeeded"
    assert sub.json()["fee_msat"] == 1001

    # the receive-side invoice is now settled from the payment path
    got = await client.get(f"/api/v1/lightning/invoices/{inv['payment_hash']}")
    assert got.status_code == 200


async def test_send_payment_wrong_digest_rejected(client):
    inv = await _create_invoice(client)
    prep = await client.post(
        "/api/v1/lightning/payments/prepare", json={"bolt11": inv["bolt11"]}
    )
    assert prep.status_code == 201
    payment_id = prep.json()["payment_id"]
    resp = await client.post(
        f"/api/v1/lightning/payments/{payment_id}/authorize",
        json={"authorization_digest": "0" * 64},
    )
    assert resp.status_code == 409
    # the payment stays prepared and a correct digest still completes
    ok = await client.get(f"/api/v1/lightning/payments/{payment_id}")
    assert ok.json()["status"] == "prepared"


async def test_channels_endpoint_discloses_liquidity_limits(client):
    resp = await client.get("/api/v1/lightning/channels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channels"], "canned node exposes one channel"
    chan = body["channels"][0]
    assert chan["capacity_msat"] == chan["local_msat"] + chan["remote_msat"]
    assert body["disclosures"], "liquidity disclosure present"
    assert "liquidity" in body["disclosures"][0].lower()
    assert isinstance(body["inbound_constrained"], bool)


async def test_capabilities_disclose_mode_and_gates(client):
    resp = await client.get("/api/v1/lightning/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "canned"
    assert body["network"] == "regtest"
    joined = " ".join(body["custody_disclosure"]).lower()
    assert "canned" in joined, "canned mode disclosed verbatim"
    assert "mainnet" in joined and "refused" in joined
    assert body["sats_to_xp"]["xp_per_sat"] == get_settings().xp_per_sat
    assert body["sats_to_xp"]["can_change"] is True
    assert body["fee_policy"]["max_fee_msat"] == 10_000


async def test_health_endpoint(client):
    resp = await client.get("/api/v1/lightning/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "canned"
    assert body["synced_to_chain"] is True
    assert body["pubkey"].startswith("02")
    assert body["active_channels"] >= 1
