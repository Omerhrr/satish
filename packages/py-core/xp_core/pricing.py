"""Published TK pricing configuration (phase 5, pricing_requirements).

One canonical conversion: ``xp_per_sat`` - TK credited per satoshi paid.
It is the ONLY rate in the system; every surface (API, bot, Mini App)
derives its display from it. The rate is published with ``can_change: true``
so clients must never cache it (pricing_requirements #1).

TK packs are the "choose a pack or enter an allowed amount" surface
(billing_flow #1): a pack is a published satoshi amount; any custom sats
amount within policy bounds is also allowed.

Task cost estimation here is a DETERMINISTIC HEURISTIC used for the
pre-task estimate (pricing_requirements #2). The agent's plan (phase 6)
produces the authoritative estimate; this heuristic exists so the API can
show an honest, stable range before any model call, plus the disclosure of
which activities may incur variable external costs (pricing_requirements #3).
"""

from __future__ import annotations

from dataclasses import dataclass

from xp_core.config import Settings

# Activities that may incur variable external costs, disclosed verbatim
# (pricing_requirements #3). Keep in sync with docs/satish-ai.md (TK credits).
VARIABLE_COST_ACTIVITIES = [
    "web.search - upstream search provider usage",
    "web.fetch_page - fetching large or slow pages",
    "docs.generate_pdf - document rendering time",
    "model usage - DeepSeek tokens are metered and reported per task",
]

MIN_PURCHASE_SATS = 100
MAX_PURCHASE_SATS = 100_000_000

MIN_BUDGET_XP = 1
MAX_BUDGET_XP = 100_000


@dataclass(slots=True)
class XpPack:
    pack_id: str
    label: str
    amount_sats: int
    xp_amount: int


def xp_for_sats(settings: Settings, amount_sats: int) -> int:
    """The canonical conversion applied everywhere credits happen."""
    return amount_sats * settings.xp_per_sat


def sats_for_xp(settings: Settings, amount_xp: int) -> int:
    """Inverse conversion for display; rounds up (never under-quotes sats)."""
    per = settings.xp_per_sat
    return -(-amount_xp // per) if per > 0 else 0


def list_packs(settings: Settings) -> list[XpPack]:
    """Published pack table built from the configured satoshi sizes."""
    packs: list[XpPack] = []
    for sats in settings.xp_pack_sats:
        if sats <= 0:
            continue
        packs.append(
            XpPack(
                pack_id=f"pack_{sats}sats",
                label=f"{sats:,} sats",
                amount_sats=sats,
                xp_amount=xp_for_sats(settings, sats),
            )
        )
    return packs


def rate_disclosure(settings: Settings) -> dict:
    """Pricing_requirements #1: publish the conversion and its mutability."""
    return {
        "xp_per_sat": settings.xp_per_sat,
        "can_change": True,
        "note": (
            "The sats-to-TK conversion is published as TK per satoshi and may "
            "change; always re-check this rate before purchasing. TK is an "
            "internal usage credit - not Bitcoin, not a blockchain token, and "
            "not a claim on funds."
        ),
    }


def estimate_task_cost_xp(objective: str) -> dict:
    """Deterministic pre-task estimate (pricing_requirements #2).

    The agent plan is authoritative; this heuristic is the stable floor that
    keeps the estimate endpoint useful (and testable) without a model call.
    Returns a range so the UI never shows false precision.
    """
    clean = (objective or "").strip()
    base = 10
    per_chars = 2 * (len(clean) // 200)
    low = base + per_chars
    return {
        "estimated_xp_low": low,
        "estimated_xp_high": low + 10,
        "basis": "deterministic heuristic; the agent plan finalizes the estimate",
        "variable_cost_activities": list(VARIABLE_COST_ACTIVITIES),
    }
