"""Buy-bitcoin links: signed per Onramper V2, mainnet-only, off when unconfigured."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from xp_core.config import Settings

ADDR = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _settings(key: Ed25519PrivateKey | None) -> Settings:
    pem = (
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode() if key else None
    )
    return Settings(_env_file=None, onramper_api_key="pk_test_abc" if key else None, onramper_signing_key=pem)


def test_signed_url_verifies_with_public_key():
    from app.api.v1.onramp import build_signed_url, canonical_string

    key = Ed25519PrivateKey.generate()
    url, _ = build_signed_url(_settings(key), ADDR, "ngn", 50000, now=datetime(2026, 10, 20, 9, 0, 0, 123000, tzinfo=UTC))
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["wallets"] == f"btc:{ADDR}" and q["defaultFiat"] == "NGN" and q["defaultAmount"] == "50000"
    assert q["sigV2Timestamp"] == "2026-10-20T09:00:00.123Z"
    assert q["sigV2Fields"] == "apiKey,defaultAmount,defaultCrypto,defaultFiat,onlyCryptos,wallets"
    fields = {k: q[k] for k in q["sigV2Fields"].split(",")}
    content = canonical_string(fields, q["sigV2Timestamp"], q["sigV2Nonce"])
    assert content.splitlines()[0] == "ONRAMPER-SIG-V2"
    assert "wallets=btc%3A" + ADDR in content  # form-encoded colon, per V2
    sig = base64.b64decode(q["sigV2"].removeprefix("v2:"))
    key.public_key().verify(sig, content.encode())  # raises if invalid


def test_tampered_address_fails_verification():
    from app.api.v1.onramp import build_signed_url, canonical_string
    from cryptography.exceptions import InvalidSignature

    key = Ed25519PrivateKey.generate()
    url, _ = build_signed_url(_settings(key), ADDR, None, None)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    fields = {k: q[k] for k in q["sigV2Fields"].split(",")}
    fields["wallets"] = "btc:bc1qattacker0000000000000000000000000000000"
    with pytest.raises(InvalidSignature):
        key.public_key().verify(base64.b64decode(q["sigV2"][3:]), canonical_string(fields, q["sigV2Timestamp"], q["sigV2Nonce"]).encode())


async def test_endpoints_off_without_keys_and_mainnet_only(client, monkeypatch):
    import app.api.v1.onramp as mod

    r = await client.get("/api/v1/onramp/status")
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = await client.post("/api/v1/onramp/link", json={"address": ADDR})
    assert r.status_code == 503

    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(mod, "get_settings", lambda: _settings(key))
    r = await client.post("/api/v1/onramp/link", json={"address": "tb1q6rz28mcfaxtmd6v789l9rrlrusdprr9pqcpvkl"})
    assert r.status_code == 422
    r = await client.post("/api/v1/onramp/link", json={"address": ADDR, "amount": 20000})
    assert r.status_code == 200 and r.json()["url"].startswith("https://buy.onramper.com?")
