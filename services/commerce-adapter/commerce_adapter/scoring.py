"""Product trend scoring with transparent signals (phase-8 deliverable #3,
acceptance #4: "Scoring factors are visible and configurable").

Design contract:

- STRUCTURAL SIGNALS ONLY. Every factor is computed from the platform's own
  retrieval record (how many permitted sources carry the product, how far
  their asking prices spread, how fresh they are, how complete the
  attributes are). There is NO demand factor, NO ad-performance factor, and
  NO availability factor — the platform cannot measure those from snapshot
  pages, and inventing them is the exact failure acceptance #3 forbids.
- VISIBLE. Every output carries the factor table: raw signal, normalized
  value, weight, inclusion decision and reason. The weight configuration is
  echoed verbatim into the output and the report.
- CONFIGURABLE. Weights come from settings (operator-controlled JSON);
  unknown factor names are refused, and an unparseable configuration falls
  back to the documented defaults WITH a disclosure — never silently.
- DETERMINISTIC. Same records + same config -> same score, always.

Normalization maps each raw signal to 0..1 with a documented formula; the
total is the weight-normalized mean over INCLUDED factors, so a factor with
insufficient data is excluded (disclosed) instead of silently counted as 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from research_adapter.provenance import Fact, SourceRecord

from commerce_adapter.classify import AVAILABILITY_KEYS, PERFORMANCE_KEYS
from commerce_adapter.freshness import FRESHNESS_SCORE, freshness_label

# Documented defaults — also the fallback when the configured JSON is invalid.
DEFAULT_FACTORS: dict[str, float] = {
    "distinct_sources": 2.0,
    "supplier_count": 1.5,
    "price_spread": 1.5,
    "freshness": 1.0,
    "attribute_completeness": 1.0,
}

# A factor is only scored when its raw signal is computable; these formulas
# are public and tested.
_SOURCE_TARGET = 3.0  # distinct_sources: 3+ ok sources -> normalized 1.0
_SUPPLIER_TARGET = 2.0  # supplier_count: 2+ supplier sources -> normalized 1.0
_SPREAD_CAP = 0.5  # price_spread: >=50% asking-price spread -> normalized 0.0

NO_DEMAND_DISCLOSURE = (
    "signals are structural supply-side observables only: this score does not "
    "measure demand, ad performance, or availability, and inventing such "
    "measures is forbidden"
)


def parse_scoring_config(raw: str | None) -> tuple[dict[str, float], bool, str]:
    """Parse the configured weights JSON.

    Returns (factors, used_defaults, note). ANY defect — unparseable JSON,
    non-object shape, unknown factor names, bad weight types — falls back to
    the documented defaults (or the last-known-good subset) and surfaces a
    note that callers MUST carry into the score output. A broken operator
    configuration degrades to the documented behavior LOUDLY; it never
    silently changes what the score means, and it never blocks runs.
    """
    if raw is None or not raw.strip():
        return dict(DEFAULT_FACTORS), False, ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return dict(DEFAULT_FACTORS), True, (
            f"configured scoring factors were invalid JSON ({exc.msg}); "
            "documented defaults were used"
        )
    if not isinstance(parsed, dict) or not parsed:
        return dict(DEFAULT_FACTORS), True, (
            "configured scoring factors were not a non-empty object; "
            "documented defaults were used"
        )
    unknown = sorted(str(k) for k in parsed if k not in DEFAULT_FACTORS)
    if unknown:
        return dict(DEFAULT_FACTORS), True, (
            f"configured scoring factors contained unknown name(s) {unknown}; "
            "documented defaults were used"
        )
    factors: dict[str, float] = {}
    bad: list[str] = []
    for name in DEFAULT_FACTORS:
        value = parsed.get(name, DEFAULT_FACTORS[name])
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            bad.append(name)
            continue
        factors[name] = float(value)
    if bad:
        return dict(DEFAULT_FACTORS), True, (
            f"configured weight(s) for {sorted(bad)} were not non-negative "
            "numbers; documented defaults were used"
        )
    return factors, False, ""


@dataclass
class FactorVerdict:
    name: str
    weight: float
    signal: str  # human-readable raw signal
    normalized: float | None
    included: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "signal": self.signal,
            "normalized": self.normalized,
            "included": self.included,
            "reason": self.reason,
        }


@dataclass
class ProductScore:
    product: str
    score: float  # 0..100
    factors: list[FactorVerdict] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    config_echo: dict[str, float] = field(default_factory=dict)
    disclosures: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "score": self.score,
            "factors": [f.as_dict() for f in self.factors],
            "excluded": list(self.excluded),
            "config_echo": dict(self.config_echo),
            "disclosures": list(self.disclosures),
            "source_ids": list(self.source_ids),
        }


def _parse_number(value: str) -> float | None:
    import re

    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", value.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def candidate_sources(
    records: list[SourceRecord], product: str | None
) -> tuple[list[SourceRecord], list[str]]:
    """Sources forming the scored candidate.

    With a product name: ok sources whose title or ``product`` fact overlaps
    at least one product token (case-insensitive). Without: every ok source
    (single candidate = the task scope). Returns (sources, disclosures).
    """
    ok = [r for r in records if r.status == "ok"]
    if not product or not product.strip():
        return ok, []
    tokens = {t for t in product.lower().split() if len(t) > 2}
    chosen: list[SourceRecord] = []
    for record in ok:
        hay = {w for w in record.title.lower().replace("-", " ").split() if len(w) > 2}
        for fact in record.facts:
            if fact.key == "product":
                hay |= {w for w in fact.value.lower().replace("-", " ").split() if len(w) > 2}
        if hay & tokens:
            chosen.append(record)
    disclosures: list[str] = []
    if not chosen and ok:
        disclosures.append(
            f"no fetched source matched product {product!r}; the candidate is empty"
        )
    return chosen, disclosures


def _factor_verdicts(
    sources: list[SourceRecord],
    weights: dict[str, float],
    required_keys: list[str],
    now: datetime | None,
) -> tuple[list[FactorVerdict], list[str]]:
    """Compute one verdict per configured factor. Pure; deterministic order."""
    verdicts: list[FactorVerdict] = []
    disclosures: list[str] = []

    # -- distinct_sources ----------------------------------------------------
    w = weights.get("distinct_sources")
    if w is not None:
        count = len(sources)
        normalized = min(count / _SOURCE_TARGET, 1.0)
        verdicts.append(
            FactorVerdict(
                "distinct_sources",
                w,
                f"{count} fetched source(s) carry this candidate",
                normalized,
                True,
                f"count/{_SOURCE_TARGET:g} capped at 1.0",
            )
        )

    # -- supplier_count --------------------------------------------------------
    w = weights.get("supplier_count")
    if w is not None:
        count = sum(
            1 for r in sources if any(f.key == "supplier" for f in r.facts)
        )
        normalized = min(count / _SUPPLIER_TARGET, 1.0)
        verdicts.append(
            FactorVerdict(
                "supplier_count",
                w,
                f"{count} distinct supplier quotation source(s)",
                normalized,
                True,
                f"count/{_SUPPLIER_TARGET:g} capped at 1.0",
            )
        )

    # -- price_spread ----------------------------------------------------------
    w = weights.get("price_spread")
    if w is not None:
        prices: list[float] = []
        currencies: dict[str, str] = {}  # source_id -> currency text
        for record in sources:
            currency = next(
                (f.value for f in record.facts if f.key == "currency"), None
            )
            for fact in record.facts:
                if fact.key in {"asking_price", "unit_price", "reserve_price"}:
                    value = _parse_number(fact.value)
                    if value is not None and value > 0:
                        prices.append(value)
                        currencies[record.source_id] = (currency or "?").upper()
        verdict: FactorVerdict | None
        if len(prices) < 2:
            verdict = FactorVerdict(
                "price_spread",
                w,
                f"{len(prices)} comparable asking price(s)",
                None,
                False,
                "needs >= 2 priced sources; a spread over one data point would "
                "be invented precision",
            )
        else:
            distinct_currencies = sorted(set(currencies.values()))
            if len(distinct_currencies) > 1:
                verdict = FactorVerdict(
                    "price_spread",
                    w,
                    f"{len(prices)} asking price(s) across currencies "
                    f"{', '.join(distinct_currencies)}",
                    None,
                    False,
                    "mixed currencies are not comparable; converting them here "
                    "would fabricate an exchange rate",
                )
            else:
                spread = (max(prices) - min(prices)) / max(prices)
                normalized = 1.0 - min(spread / _SPREAD_CAP, 1.0)
                verdict = FactorVerdict(
                    "price_spread",
                    w,
                    f"asking-price spread {spread:.1%} over {len(prices)} "
                    f"{distinct_currencies[0]} prices",
                    normalized,
                    True,
                    f"1 - min(spread/{_SPREAD_CAP:g}, 1); tighter spread scores higher",
                )
                disclosures.append(
                    "price spread measures how far apart asking prices are; it is "
                    "a price-dispersion signal, not a demand estimate"
                )
        if verdict is not None:
            verdicts.append(verdict)

    # -- freshness ---------------------------------------------------------------
    w = weights.get("freshness")
    if w is not None:
        if not sources:
            verdicts.append(
                FactorVerdict(
                    "freshness", w, "no fetched sources", None, False,
                    "freshness needs at least one retrieved source",
                )
            )
        else:
            labels = [freshness_label(r.retrieved_at, now) for r in sources]
            scores = [FRESHNESS_SCORE[label] for label in labels]
            normalized = sum(scores) / len(scores)
            verdicts.append(
                FactorVerdict(
                    "freshness",
                    w,
                    f"retrieval freshness {labels.count('fresh')} fresh / "
                    f"{labels.count('recent')} recent / {labels.count('stale')} stale / "
                    f"{labels.count('outdated')} outdated",
                    normalized,
                    True,
                    "mean of fresh=1.0 recent=0.66 stale=0.33 outdated=0.0",
                )
            )

    # -- attribute_completeness ----------------------------------------------------
    w = weights.get("attribute_completeness")
    if w is not None:
        if not required_keys:
            verdicts.append(
                FactorVerdict(
                    "attribute_completeness", w, "no required attribute list given",
                    None, False,
                    "pass required_keys (the attributes the use case needs) to "
                    "score completeness",
                )
            )
        else:
            present = set()
            for record in sources:
                present |= {f.key for f in record.facts}
            covered = [k for k in required_keys if k in present]
            normalized = len(covered) / len(required_keys)
            verdicts.append(
                FactorVerdict(
                    "attribute_completeness",
                    w,
                    f"{len(covered)}/{len(required_keys)} required attributes present",
                    normalized,
                    True,
                    "covered/required",
                )
            )

    return verdicts, disclosures


def score_product(
    records: list[SourceRecord],
    *,
    weights: dict[str, float],
    product: str | None = None,
    required_keys: list[str] | None = None,
    now: datetime | None = None,
) -> ProductScore:
    """Score one candidate product from the task's collected sources.

    Same records + weights -> same verdict. The weight configuration is
    echoed verbatim (config_echo); factors with insufficient data are
    excluded with reasons, and the score is the weight-normalized mean over
    included factors only.
    """
    sources, disclosures = candidate_sources(records, product)
    verdicts, factor_disclosures = _factor_verdicts(
        sources, weights, list(required_keys or []), now
    )
    disclosures.extend(factor_disclosures)
    disclosures.append(NO_DEMAND_DISCLOSURE)

    included = [v for v in verdicts if v.included and v.normalized is not None]
    excluded = [v.name for v in verdicts if not v.included]
    if included:
        total_weight = sum(v.weight for v in included)
        score = sum(v.weight * (v.normalized or 0.0) for v in included) / total_weight * 100
    else:
        score = 0.0
        disclosures.append(
            "no factor had enough data to include; the score is 0.0 by "
            "convention and MUST NOT be read as a negative verdict"
        )

    # Guard the honesty contract structurally: no performance or availability
    # key can ever become a scoring factor, whatever a page claims.
    for record in sources:
        banned = PERFORMANCE_KEYS | AVAILABILITY_KEYS
        leaked = sorted({f.key for f in record.facts if f.key in banned})
        if leaked:
            disclosures.append(
                "page-reported performance/availability fields "
                f"({', '.join(leaked)}) were recorded as provenance but are "
                "excluded from every signal"
            )
            break

    return ProductScore(
        product=product or "task scope",
        score=round(score, 1),
        factors=verdicts,
        excluded=excluded,
        config_echo=dict(weights),
        disclosures=disclosures,
        source_ids=[r.source_id for r in sources],
    )


def score_records(
    records: list[SourceRecord],
    *,
    product: str | None = None,
    required_keys: list[str] | None = None,
    now: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> ProductScore:
    """Convenience wrapper resolving weights (defaults when not given)."""
    return score_product(
        records,
        weights=weights if weights is not None else dict(DEFAULT_FACTORS),
        product=product,
        required_keys=required_keys,
        now=now,
    )


def fact_value(record: SourceRecord, key: str) -> Fact | None:
    return next((f for f in record.facts if f.key == key), None)


__all__ = [
    "DEFAULT_FACTORS",
    "NO_DEMAND_DISCLOSURE",
    "FactorVerdict",
    "ProductScore",
    "candidate_sources",
    "parse_scoring_config",
    "score_product",
    "score_records",
]
