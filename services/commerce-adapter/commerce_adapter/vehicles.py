"""Vehicle auction research workflow (phase-8 deliverable #5).

The user supplies EXPLICIT specifications (make, model, year bounds, mileage
cap, budget cap); every fetched vehicle source is checked against them.
Matches and mismatches are both first-class cited facts - a mismatched
listing is information, not an error. Cross-source value conflicts (two
sources, different mileage for the same vehicle) are surfaced, never
averaged away.

No auction, lot, or seller is ever invented: only fetched sources are
checked, and listed-but-never-fetched sources are disclosed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from research_adapter.provenance import SourceRecord

VEHICLE_KEYS = {"make", "model", "year", "mileage_km", "trim"}
VEHICLE_PRICE_KEYS = {"asking_price", "reserve_price"}

# spec key -> comparison rule
_EXACT_KEYS = {"make", "model", "transmission", "fuel", "drive", "condition_grade"}
_BOUND_RULES = {
    "year_min": ("year", "min"),
    "year_max": ("year", "max"),
    "mileage_km_max": ("mileage_km", "max"),
    "mileage_km_min": ("mileage_km", "min"),
    "budget_max": ("_price", "max"),
    "budget_min": ("_price", "min"),
}

_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _number(value: str) -> float | None:
    match = _NUM.search(value.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


@dataclass
class VehicleCheckRow:
    source_id: str
    citation: str
    title: str
    matches: list[str] = field(default_factory=list)
    mismatches: list[dict[str, str]] = field(default_factory=list)
    prices: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "citation": self.citation,
            "title": self.title,
            "matches": self.matches,
            "mismatches": self.mismatches,
            "prices": self.prices,
        }


@dataclass
class VehicleCheckResult:
    rows: list[VehicleCheckRow] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": [r.as_dict() for r in self.rows],
            "conflicts": self.conflicts,
            "disclosures": self.disclosures,
        }


def is_vehicle_source(record: SourceRecord) -> bool:
    keys = {f.key for f in record.facts}
    return bool(keys & VEHICLE_KEYS)


def check_vehicles(
    records: list[SourceRecord],
    specs: dict[str, str],
) -> VehicleCheckResult:
    """Check fetched vehicle sources against the user's explicit specs.

    Spec keys: exact-match fields (make/model/...) compare case-insensitively;
    bound fields (year_min/year_max/mileage_km_max/mileage_km_min/budget_max/
    budget_min) compare numerically against year/mileage_km/asking-or-reserve
    price. Unknown spec keys are refused up front (the tool schema narrows
    them, and this is the second wall).
    """
    result = VehicleCheckResult()
    unknown = sorted(set(specs) - set(_EXACT_KEYS) - set(_BOUND_RULES))
    if unknown:
        result.disclosures.append(
            f"unknown spec key(s) {unknown} were ignored; known keys: "
            f"{sorted(set(_EXACT_KEYS) | set(_BOUND_RULES))}"
        )

    ordered = [r for r in records if r.status == "ok"]
    label_of = {r.source_id: f"[S{i}]" for i, r in enumerate(records, start=1)}
    vehicles = [r for r in ordered if is_vehicle_source(r)]
    for record in records:
        if record.status == "listed":
            result.disclosures.append(
                f"source {label_of.get(record.source_id, '[S?]')} {record.url} was listed "
                "by search but never fetched - it contributes no vehicle data"
            )
    if not vehicles:
        result.disclosures.append(
            "no fetched source carried vehicle attributes; no auction or lot is "
            "invented to fill the gap"
        )
        return result

    for record in vehicles:
        row = VehicleCheckRow(
            source_id=record.source_id,
            citation=label_of.get(record.source_id, "[S?]"),
            title=record.title,
        )
        facts = {f.key: f for f in record.facts}
        for spec_key, expected in specs.items():
            expected_text = str(expected).strip()
            if spec_key in _EXACT_KEYS:
                fact = facts.get(spec_key)
                if fact is None:
                    continue  # absence is a gap, not a mismatch
                if fact.value.strip().casefold() == expected_text.casefold():
                    row.matches.append(spec_key)
                else:
                    row.mismatches.append(
                        {"key": spec_key, "expected": expected_text, "actual": fact.value}
                    )
            elif spec_key in _BOUND_RULES:
                fact_key, direction = _BOUND_RULES[spec_key]
                bound = _number(expected_text)
                if bound is None:
                    row.mismatches.append(
                        {
                            "key": spec_key,
                            "expected": expected_text,
                            "actual": "not a number",
                        }
                    )
                    continue
                if fact_key == "_price":
                    candidates = [
                        facts[k]
                        for k in sorted(VEHICLE_PRICE_KEYS)
                        if k in facts and _number(facts[k].value) is not None
                    ]
                    fact = candidates[0] if candidates else None
                    actual = _number(fact.value) if fact else None
                else:
                    fact = facts.get(fact_key)
                    actual = _number(fact.value) if fact else None
                if fact is None or actual is None:
                    continue  # a bound over a missing attribute is a gap
                ok = actual <= bound if direction == "max" else actual >= bound
                if ok:
                    row.matches.append(spec_key)
                else:
                    op = "<=" if direction == "max" else ">="
                    row.mismatches.append(
                        {
                            "key": spec_key,
                            "expected": (
                                f"{spec_key.rsplit('_', 1)[0].replace('_', ' ')} "
                                f"{op} {bound:g}"
                            ),
                            "actual": fact.value,
                        }
                    )
        for key in sorted(VEHICLE_PRICE_KEYS):
            fact = facts.get(key)
            if fact is not None:
                row.prices.append(
                    {"key": key, "value": fact.value, "kind": fact.kind, "note": fact.note or ""}
                )
        result.rows.append(row)

    # cross-source conflicts on shared vehicle attributes
    subjects: dict[str, list[tuple[SourceRecord, str]]] = {}
    for record in vehicles:
        for fact in record.facts:
            if fact.key in VEHICLE_KEYS | VEHICLE_PRICE_KEYS | {"currency"}:
                subjects.setdefault(fact.key, []).append((record, fact.value))
    for key in sorted(subjects):
        entries = subjects[key]
        distinct: list[str] = []
        for _record, value in entries:
            if not any(_same(value, d) for d in distinct):
                distinct.append(value)
        if len(distinct) > 1:
            result.conflicts.append(
                {
                    "subject": key,
                    "detail": (
                        f"{len(distinct)} differing values for '{key}' across "
                        f"{len(entries)} vehicle sources"
                    ),
                    "values": [
                        {
                            "citation": label_of.get(r.source_id, "[S?]"),
                            "value": v,
                        }
                        for r, v in entries
                    ],
                }
            )
    return result


def _same(a: str, b: str) -> bool:
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    return a.strip().casefold() == b.strip().casefold()


__all__ = ["VehicleCheckResult", "VehicleCheckRow", "check_vehicles", "is_vehicle_source"]
