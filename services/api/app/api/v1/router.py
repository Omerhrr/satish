"""Aggregated /api/v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import artifacts, auth, health, tasks, wallets, xp

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(xp.router)
api_router.include_router(tasks.router)
api_router.include_router(artifacts.router)
api_router.include_router(wallets.router)
