"""Commerce fact classification (phase-8 deliverable #2 / acceptance #2).

Extends the research provenance typing with commerce source semantics. The
three-way distinction the reports must make:

- asking prices  -> ``estimate``  (market/auction/dealer listings and
  supplier quotations are SNAPSHOTS; they are what someone asks, not what
  was paid)
- observed facts -> ``observed``  (including OFFICIAL published rates —
  tariff/fee schedules — which are the closest thing to verified costs
  this pipeline can ground)
- verified costs -> none exist here, and every consumer says so: nothing
  in the collected evidence is a confirmed transaction price. The landed
  cost template states that absence explicitly.

Never invented: facts only come from extracted page text; classification
only relabels, it never adds values.
"""

from __future__ import annotations

from datetime import datetime

from research_adapter.provenance import Fact

# corpus source_type values -> behavior
LISTING_TYPES = {"market", "auction", "dealer", "ad_library"}
SUPPLIER_TYPES = {"supplier"}
OFFICIAL_TYPES = {"official"}

# price-ish keys (superset of research PRICE_KEYS relevant to commerce)
COMMERCE_PRICE_KEYS = {
    "price",
    "asking_price",
    "listed_price",
    "unit_price",
    "current_price",
    "reserve_price",
    "shipping_total",
    "buyer_fee",
}

# keys that on an OFFICIAL source are published rates -> observed
OFFICIAL_RATE_KEYS = {"duty_rate_pct", "levy_pct", "vat_rate_pct", "fee_pct", "buyer_premium_pct"}

# performance-metric keys: recorded if a page literally prints them, but
# NEVER summarized, scored, or reported as findings (acceptance #3)
PERFORMANCE_KEYS = {
    "ctr",
    "impressions",
    "reach",
    "clicks",
    "engagement",
    "engagement_rate",
    "cpc",
    "cpm",
    "conversions",
    "roas",
}

# availability-ish keys: echoed as page facts, never used as scoring signals
AVAILABILITY_KEYS = {"stock_status", "availability", "in_stock", "stock_count"}


def commerce_facts(
    extracted: list[tuple[str, str]],
    *,
    source_type: str,
    retrieved_at: datetime | None,
) -> list[Fact]:
    """Classify extracted key/value pairs for a commerce source of a type.

    Deterministic rules, same note wording as the research pipeline where
    they overlap, so reports read consistently.
    """
    out: list[Fact] = []
    stamp = retrieved_at.strftime("%Y-%m-%d %H:%M UTC") if retrieved_at else "an unknown time"
    for key, value in extracted:
        k = key.strip().lower()
        if source_type in LISTING_TYPES and k in COMMERCE_PRICE_KEYS:
            out.append(
                Fact(
                    key=k,
                    value=value,
                    kind="estimate",
                    note=f"asking price snapshot retrieved at {stamp}, not a live quote",
                )
            )
        elif source_type in SUPPLIER_TYPES and k in COMMERCE_PRICE_KEYS:
            out.append(
                Fact(
                    key=k,
                    value=value,
                    kind="estimate",
                    note=f"supplier quotation snapshot retrieved at {stamp}, "
                    "not a verified cost",
                )
            )
        elif source_type in OFFICIAL_TYPES and k in OFFICIAL_RATE_KEYS:
            out.append(
                Fact(
                    key=k,
                    value=value,
                    kind="observed",
                    note="official published rate",
                )
            )
        else:
            out.append(Fact(key=k, value=value, kind="observed"))
    return out


def performance_facts(facts: list[Fact]) -> list[Fact]:
    """The subset of facts that are ad-performance metrics (present in page
    text but excluded from every summary and score)."""
    return [f for f in facts if f.key in PERFORMANCE_KEYS]


def availability_facts(facts: list[Fact]) -> list[Fact]:
    """Availability-ish facts the page stated (echoed, never asserted)."""
    return [f for f in facts if f.key in AVAILABILITY_KEYS]


__all__ = [
    "AVAILABILITY_KEYS",
    "COMMERCE_PRICE_KEYS",
    "LISTING_TYPES",
    "OFFICIAL_RATE_KEYS",
    "OFFICIAL_TYPES",
    "PERFORMANCE_KEYS",
    "SUPPLIER_TYPES",
    "availability_facts",
    "commerce_facts",
    "performance_facts",
]
