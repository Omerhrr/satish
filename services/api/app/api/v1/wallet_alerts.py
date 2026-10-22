"""Opt-in Telegram messages when the user's wallet receives bitcoin."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from xp_core.services import wallet_alerts as svc

from app.deps import CurrentUser, DbSession

router = APIRouter(prefix="/wallet/alerts", tags=["wallet-alerts"])

Network = Literal["mainnet", "testnet"]


class AlertsOut(BaseModel):
    enabled: bool
    watched: int


class AlertsIn(BaseModel):
    network: Network
    enabled: bool
    addresses: list[str] = Field(default_factory=list, max_length=50)


class WatchIn(BaseModel):
    network: Network
    addresses: list[str] = Field(min_length=1, max_length=50)


@router.get("", response_model=AlertsOut)
async def get_alerts(user: CurrentUser, session: DbSession, network: Network) -> AlertsOut:
    return AlertsOut(**await svc.status(session, user, network))


@router.put("", response_model=AlertsOut)
async def set_alerts(body: AlertsIn, user: CurrentUser, session: DbSession) -> AlertsOut:
    try:
        return AlertsOut(**await svc.set_enabled(session, user, body.network, body.enabled, body.addresses))
    except svc.AlertError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/addresses", response_model=AlertsOut)
async def watch(body: WatchIn, user: CurrentUser, session: DbSession) -> AlertsOut:
    try:
        await svc.add_addresses(session, user, body.network, body.addresses)
    except svc.AlertError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return AlertsOut(**await svc.status(session, user, body.network))
