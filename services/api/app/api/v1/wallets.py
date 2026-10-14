"""Wallets + lightning scaffold endpoints.

Phase 1 only shapes the contract. Real flows wait on the documented
threat-model and integration spikes (bitcoin_and_lightning.decision_process);
the wallet_adapter / lightning_adapter protocols keep the choice replaceable.
"""

from __future__ import annotations

from fastapi import APIRouter
from xp_core.schemas.api import CapabilitiesOut

from app.api.v1.health import capabilities

router = APIRouter(tags=["wallets"])


@router.get("/capabilities", response_model=CapabilitiesOut, include_in_schema=False)
async def capabilities_alias() -> CapabilitiesOut:
    return await capabilities()
