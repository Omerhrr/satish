"""Aggregated /api/v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    account,
    artifacts,
    auth,
    automation,
    connections,
    drafts,
    handles,
    health,
    lightning,
    notifications,
    onramp,
    ops,
    price,
    tasks,
    wallet_alerts,
    xp,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(handles.router)
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(xp.router)
api_router.include_router(tasks.router)
api_router.include_router(artifacts.router)
api_router.include_router(lightning.router)
api_router.include_router(connections.router)
api_router.include_router(drafts.router)
api_router.include_router(automation.router)
api_router.include_router(notifications.router)
api_router.include_router(onramp.router)
api_router.include_router(ops.router)
api_router.include_router(price.router)
api_router.include_router(wallet_alerts.router)
