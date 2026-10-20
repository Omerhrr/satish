"""Buy bitcoin: signed Onramper links that deliver to the user's OWN address.

XP never sells bitcoin or holds money. A licensed provider (chosen by the
user inside the Onramper widget) takes the payment and sends the bitcoin
straight to the wallet address the user's phone generated. The server only
signs the link so that address can't be tampered with in transit.

Signing follows Onramper "Widget: Sign a URL (V2)": canonical 8-line string,
Ed25519 signature, base64 with a ``v2:`` prefix.
"""

from __future__ import annotations

import base64
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from xp_core.config import Settings, get_settings
from xp_core.logging import get_logger

from app.deps import CurrentUser

log = get_logger(__name__)
router = APIRouter(prefix="/onramp", tags=["onramp"])

# Mainnet only: bech32 (bc1…) or legacy base58 (1…/3…). Providers only sell real BTC.
MAINNET_ADDRESS = re.compile(r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
LINK_TTL_MINUTES = 15


class OnrampStatusOut(BaseModel):
    enabled: bool
    default_fiat: str


class OnrampLinkIn(BaseModel):
    address: str = Field(min_length=26, max_length=90)
    fiat: str | None = Field(default=None, min_length=3, max_length=3)
    amount: float | None = Field(default=None, gt=0, le=100_000_000)


class OnrampLinkOut(BaseModel):
    url: str
    expires_at: str


def _enabled(s: Settings) -> bool:
    return bool(s.onramper_api_key and s.onramper_signing_key)


def _private_key(pem: str) -> Ed25519PrivateKey:
    key = load_pem_private_key(pem.replace("\\n", "\n").encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("onramper signing key must be Ed25519")
    return key


def canonical_string(fields: dict[str, str], timestamp: str, nonce: str) -> str:
    query = urlencode(sorted(fields.items()))
    return "\n".join(["ONRAMPER-SIG-V2", timestamp, nonce, "GET", "/", query, "", EMPTY_SHA256])


def build_signed_url(
    s: Settings, address: str, fiat: str | None, amount: float | None, *, now: datetime | None = None
) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    fields = {
        "apiKey": s.onramper_api_key or "",
        "wallets": f"btc:{address}",
        "onlyCryptos": "btc",
        "defaultCrypto": "btc",
        "defaultFiat": (fiat or s.onramper_default_fiat).upper(),
    }
    if amount:
        fields["defaultAmount"] = f"{amount:g}"
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    nonce = str(uuid.uuid4())
    expiry = now + timedelta(minutes=LINK_TTL_MINUTES)
    signature = _private_key(s.onramper_signing_key or "").sign(
        canonical_string(fields, timestamp, nonce).encode()
    )
    params = dict(sorted(fields.items()))
    params.update(
        {
            "mode": "buy",
            "redirectAtCheckout": "false",
            "themeName": "dark",
            "sigV2": "v2:" + base64.b64encode(signature).decode(),
            "sigV2Timestamp": timestamp,
            "sigV2Nonce": nonce,
            "sigV2Fields": ",".join(sorted(fields)),
            "sigV2Expiry": expiry.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
    )
    return f"{s.onramper_widget_url}?{urlencode(params)}", expiry


@router.get("/status", response_model=OnrampStatusOut)
async def onramp_status() -> OnrampStatusOut:
    s = get_settings()
    return OnrampStatusOut(enabled=_enabled(s), default_fiat=s.onramper_default_fiat)


@router.post("/link", response_model=OnrampLinkOut)
async def onramp_link(payload: OnrampLinkIn, user: CurrentUser) -> OnrampLinkOut:
    s = get_settings()
    if not _enabled(s):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Buying bitcoin in the app isn't switched on yet.",
        )
    address = payload.address.strip()
    if not MAINNET_ADDRESS.match(address):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Buying needs a real-bitcoin wallet address (starting with bc1, 1 or 3).",
        )
    try:
        url, expiry = build_signed_url(s, address, payload.fiat, payload.amount)
    except ValueError as exc:
        log.error("onramp_signing_failed", reason=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Buying is temporarily unavailable.") from exc
    log.info("onramp_link_created", user_id=user.id, fiat=payload.fiat or s.onramper_default_fiat)
    return OnrampLinkOut(url=url, expires_at=expiry.isoformat())
