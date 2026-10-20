"""Bitcoin price in naira (and USD), for showing "≈ ₦" next to amounts.

Fetched from CoinGecko at most every PRICE_TTL_SECONDS and shared by all
users, so the app never hammers the source. If CoinGecko is down the last
good price is served with its age; with no price at all the app simply hides
the naira line. Display only: nothing is ever charged at this rate.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from xp_core.config import get_settings
from xp_core.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/price", tags=["price"])

SOURCE_URL = "https://api.coingecko.com/api/v3/simple/price"
PRICE_TTL_SECONDS = 120
_cache: dict[str, float] = {}


class PriceOut(BaseModel):
    btc_ngn: float
    btc_usd: float | None
    updated_at: int  # unix seconds
    source: str = "CoinGecko"


async def _fetch(transport: httpx.AsyncBaseTransport | None = None) -> None:
    headers = {"Accept": "application/json"}
    key = get_settings().coingecko_api_key
    if key:
        headers["x-cg-demo-api-key"] = key
    async with httpx.AsyncClient(timeout=8, transport=transport) as client:
        resp = await client.get(SOURCE_URL, params={"ids": "bitcoin", "vs_currencies": "ngn,usd"}, headers=headers)
    resp.raise_for_status()
    btc = resp.json()["bitcoin"]
    _cache.update(btc_ngn=float(btc["ngn"]), btc_usd=float(btc.get("usd") or 0) or 0.0, at=time.time())


async def current_price(transport: httpx.AsyncBaseTransport | None = None) -> dict[str, float]:
    if not _cache or time.time() - _cache["at"] > PRICE_TTL_SECONDS:
        try:
            await _fetch(transport)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("price_fetch_failed", error=str(exc), have_cached=bool(_cache))
    return _cache


@router.get("/btc", response_model=PriceOut)
async def btc_price() -> PriceOut:
    p = await current_price()
    if not p:
        raise HTTPException(status_code=503, detail="Price isn't available right now.")
    return PriceOut(btc_ngn=p["btc_ngn"], btc_usd=p["btc_usd"] or None, updated_at=int(p["at"]))
