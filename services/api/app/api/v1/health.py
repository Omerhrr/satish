"""Health and capabilities endpoints (Phase 1 acceptance: health checks work)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from xp_core.config import get_settings
from xp_core.schemas.api import CapabilitiesOut, ComponentStatus, HealthOut

from app.deps import DbSession

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


async def _db_status(session: DbSession) -> ComponentStatus:
    try:
        await session.execute(text("SELECT 1"))
        return ComponentStatus(name="database", status="ok")
    except Exception as exc:
        return ComponentStatus(name="database", status="error", detail=str(exc)[:200])


@router.get("/health", response_model=HealthOut)
async def health(session: DbSession) -> HealthOut:
    settings = get_settings()
    db = await _db_status(session)
    queue = (
        ComponentStatus(name="queue", status="ok", detail=settings.redis_url)
        if settings.redis_url
        else ComponentStatus(
            name="queue", status="not_configured", detail="inline dev execution (no redis)"
        )
    )
    agent = (
        ComponentStatus(name="agent_runtime", status="ok", detail=settings.deepseek_base_url)
        if settings.deepseek_api_key
        else ComponentStatus(
            name="agent_runtime",
            status="not_configured",
            detail="DEEPSEEK_API_KEY not set; adapter runs in deterministic stub mode",
        )
    )
    overall = "ok" if db.status == "ok" else "degraded"
    return HealthOut(
        status=overall,  # type: ignore[arg-type]
        env=settings.env,
        version=VERSION,
        database=db,
        queue=queue,
        agent_runtime=agent,
        dsh_revision=settings.dsh_revision,
    )


@router.get("/capabilities", response_model=CapabilitiesOut)
async def capabilities() -> CapabilitiesOut:
    """Honest capability surface — what is real today vs. pending spikes."""
    return CapabilitiesOut(
        wallets="pending_integration_spike (phase 3)",
        lightning="pending_implementation_poc (phase 3+)",
        agent_runtime="adapter scaffolded; DSH revision unpinned (phase 0 spike)",
        notes=[
            "Wallet and Lightning adapters are replaceable protocols by design.",
            "No private key or seed material ever passes through this API.",
            "XP is an internal usage credit; it is not Bitcoin and not a token.",
        ],
    )
