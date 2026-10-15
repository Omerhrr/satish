"""Commerce intelligence adapter (phase 8).

Deterministic, honesty-first commerce tooling over the task's collected
provenance records:

- classify      commerce fact typing: asking prices are estimates, official
                published rates are observed, page performance/availability
                metrics are recorded but NEVER summarized or scored
- scoring       product trend scoring from STRUCTURAL signals only, with a
                visible, operator-configurable factor table (no demand, no
                ad performance, no availability measures)
- suppliers     supplier-vs-listing comparison with citations and conflicts
- vehicles      auction/dealer vehicle checks against explicit user specs
- adlibrary     canned ad-library fixture integration that labels itself and
                refuses to invent demand or performance claims
- landed        landed-cost estimate template with typed lines and the
                explicit "no verified cost exists here" disclosure
- freshness     source freshness + confidence indicators
- eval          the committed repeatable commerce evaluation set runner
"""

from commerce_adapter.adlibrary import (
    AD_ATTRIBUTE_KEYS,
    CANNED_DISCLOSURE,
    NO_PERFORMANCE_DISCLOSURE,
    AdLibraryOutcome,
    CannedAdLibraryProvider,
    summarize_ad,
)
from commerce_adapter.classify import (
    AVAILABILITY_KEYS,
    COMMERCE_PRICE_KEYS,
    LISTING_TYPES,
    OFFICIAL_RATE_KEYS,
    OFFICIAL_TYPES,
    PERFORMANCE_KEYS,
    SUPPLIER_TYPES,
    availability_facts,
    commerce_facts,
    performance_facts,
)
from commerce_adapter.freshness import (
    FRESHNESS_ORDER,
    FRESHNESS_SCORE,
    confidence_label,
    freshness_label,
)
from commerce_adapter.landed import (
    CostLine,
    LandedCostError,
    LandedCostResult,
    compute_landed_cost,
)
from commerce_adapter.providers import CommerceFetchOutcome, CommerceFetchProvider
from commerce_adapter.scoring import (
    DEFAULT_FACTORS,
    NO_DEMAND_DISCLOSURE,
    FactorVerdict,
    ProductScore,
    candidate_sources,
    parse_scoring_config,
    score_product,
    score_records,
)
from commerce_adapter.suppliers import (
    COMPARE_KEYS,
    SupplierComparison,
    SupplierRow,
    compare_suppliers,
)
from commerce_adapter.vehicles import (
    VehicleCheckResult,
    VehicleCheckRow,
    check_vehicles,
    is_vehicle_source,
)

__all__ = [
    "AD_ATTRIBUTE_KEYS",
    "AVAILABILITY_KEYS",
    "CANNED_DISCLOSURE",
    "COMMERCE_PRICE_KEYS",
    "COMPARE_KEYS",
    "DEFAULT_FACTORS",
    "FRESHNESS_ORDER",
    "FRESHNESS_SCORE",
    "LISTING_TYPES",
    "NO_DEMAND_DISCLOSURE",
    "NO_PERFORMANCE_DISCLOSURE",
    "OFFICIAL_RATE_KEYS",
    "OFFICIAL_TYPES",
    "PERFORMANCE_KEYS",
    "SUPPLIER_TYPES",
    "AdLibraryOutcome",
    "CannedAdLibraryProvider",
    "CommerceFetchOutcome",
    "CommerceFetchProvider",
    "CostLine",
    "FactorVerdict",
    "LandedCostError",
    "LandedCostResult",
    "ProductScore",
    "SupplierComparison",
    "SupplierRow",
    "VehicleCheckResult",
    "VehicleCheckRow",
    "availability_facts",
    "candidate_sources",
    "check_vehicles",
    "commerce_facts",
    "compare_suppliers",
    "compute_landed_cost",
    "confidence_label",
    "freshness_label",
    "is_vehicle_source",
    "parse_scoring_config",
    "performance_facts",
    "score_product",
    "score_records",
    "summarize_ad",
]
