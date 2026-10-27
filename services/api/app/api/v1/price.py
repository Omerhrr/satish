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


# Every fiat currency: BTC/USD from CoinGecko for the ones it quotes directly
# (market rates, e.g. NGN tracks the exchanges, not the official rate), and
# USD cross rates from open.er-api.com (free, no key) for the rest.
CG_FIAT = (
    "usd,eur,gbp,ngn,zar,inr,cad,aud,jpy,cny,aed,sar,brl,mxn,chf,sek,nok,dkk,pln,try,"
    "krw,idr,php,thb,vnd,myr,sgd,hkd,nzd,pkr,bdt,ils,egp,kwd,bhd,czk,huf,uah,ars,clp,lkr,twd"
)
FX_URL = "https://open.er-api.com/v6/latest/USD"
RATES_TTL_SECONDS = 300
_rates: dict[str, object] = {}


class RatesOut(BaseModel):
    btc: dict[str, float]  # currency code (upper) -> price of 1 BTC
    updated_at: int
    source: str = "CoinGecko + open.er-api.com"


async def _fetch_rates(transport: httpx.AsyncBaseTransport | None = None) -> None:
    headers = {"Accept": "application/json"}
    key = get_settings().coingecko_api_key
    if key:
        headers["x-cg-demo-api-key"] = key
    out: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=8, transport=transport) as client:
        cg = await client.get(SOURCE_URL, params={"ids": "bitcoin", "vs_currencies": CG_FIAT}, headers=headers)
        cg.raise_for_status()
        for code, v in (cg.json().get("bitcoin") or {}).items():
            if v:
                out[code.upper()] = float(v)
        try:
            fx = await client.get(FX_URL)
            fx.raise_for_status()
            usd = out.get("USD")
            for code, per_usd in (fx.json().get("rates") or {}).items():
                if usd and code.upper() not in out and per_usd:
                    out[code.upper()] = usd * float(per_usd)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("fx_fetch_failed", error=str(exc))
    if out:
        _rates.update(btc=out, at=time.time())


async def current_rates(transport: httpx.AsyncBaseTransport | None = None) -> dict[str, object]:
    if not _rates or time.time() - float(_rates["at"]) > RATES_TTL_SECONDS:
        try:
            await _fetch_rates(transport)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("rates_fetch_failed", error=str(exc), have_cached=bool(_rates))
    return _rates


@router.get("/rates", response_model=RatesOut)
async def rates() -> RatesOut:
    r = await current_rates()
    if not r:
        raise HTTPException(status_code=503, detail="Prices aren't available right now.")
    return RatesOut(btc=r["btc"], updated_at=int(r["at"]))  # type: ignore[arg-type]


@router.get("/btc", response_model=PriceOut)
async def btc_price() -> PriceOut:
    p = await current_price()
    if not p:
        raise HTTPException(status_code=503, detail="Price isn't available right now.")
    return PriceOut(btc_ngn=p["btc_ngn"], btc_usd=p["btc_usd"] or None, updated_at=int(p["at"]))
