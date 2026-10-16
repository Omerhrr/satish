"""Supplier and listing comparison (phase-8 deliverable #4).

Partitions the task's fetched sources into SUPPLIER QUOTATIONS vs MARKET
LISTINGS vs OFFICIAL SCHEDULES and compares them on the keys that matter
for sourcing decisions (unit price, MOQ, lead time, shipping, warranty,
published duty rates). Every value keeps its [S{n}] citation and its fact
kind, so asking prices stay estimates and official rates stay observed.

Conflicts are surfaced, never averaged away. The comparison NEVER invents
supplier quotations: only fetched sources participate, and sources listed
by search but never fetched are disclosed as contributing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research_adapter.compare import _same_value  # shared agreement rule
from research_adapter.provenance import SourceRecord

COMPARE_KEYS = (
    "unit_price",
    "currency",
    "moq",
    "lead_time_days",
    "shipping_total",
    "warranty_months",
    "asking_price",
    "duty_rate_pct",
    "buyer_premium_pct",
)


@dataclass
class SupplierRow:
    subject: str
    values: list[dict[str, Any]] = field(default_factory=list)
    conflict: bool = False


@dataclass
class SupplierComparison:
    suppliers: list[dict[str, Any]] = field(default_factory=list)
    official: list[dict[str, Any]] = field(default_factory=list)
    rows: list[SupplierRow] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "suppliers": self.suppliers,
            "official": self.official,
            "rows": [
                {
                    "subject": r.subject,
                    "conflict": r.conflict,
                    "values": r.values,
                }
                for r in self.rows
            ],
            "conflicts": self.conflicts,
            "gaps": self.gaps,
            "disclosures": self.disclosures,
        }


def _role_of(record: SourceRecord, source_types: dict[str, str]) -> str:
    """supplier | market | official | unknown, from the persisted note header
    set at fetch time (commerce_tools records source_type in the note)."""
    st = source_types.get(record.source_id, "")
    if st in {"supplier"}:
        return "supplier"
    if st in {"official"}:
        return "official"
    if st in {"market", "auction", "dealer"}:
        return "market"
    return "unknown"


def compare_suppliers(
    records: list[SourceRecord],
    source_types: dict[str, str] | None = None,
    required_keys: list[str] | None = None,
) -> SupplierComparison:
    """Compare supplier quotations and market listings with citations.

    ``source_types`` maps source_id -> corpus source_type; the API layer
    persists it in the research_sources note header at fetch time so the
    comparison stays deterministic across restarts.
    """
    types = source_types or {}
    result = SupplierComparison()
    ordered = [r for r in records if r.status == "ok"]
    label_of = {r.source_id: f"[S{i}]" for i, r in enumerate(records, start=1)}

    for record in ordered:
        role = _role_of(record, types)
        supplier_name = next(
            (f.value for f in record.facts if f.key == "supplier"), None
        )
        entry = {
            "source_id": record.source_id,
            "citation": label_of.get(record.source_id, "[S?]"),
            "url": record.url,
            "title": record.title,
            "supplier": supplier_name,
            "facts": [f.as_dict() for f in record.facts],
        }
        if role == "supplier":
            result.suppliers.append(entry)
        elif role == "official":
            result.official.append(entry)

    if not result.suppliers:
        result.disclosures.append(
            "no fetched supplier quotations were collected; nothing here is a "
            "supplier quote and none will be invented"
        )
    if not result.official:
        result.disclosures.append(
            "no official published rate source was fetched; any duty/fee figure "
            "in this comparison is an assumption, not a verified cost"
        )
    for record in records:
        if record.status == "listed":
            result.disclosures.append(
                f"source {label_of.get(record.source_id, '[S?]')} {record.url} was "
                "listed by search but never fetched - it contributes no quote"
            )

    # rows over the sourcing keys, all cited
    subjects: dict[str, SupplierRow] = {}
    for record in ordered:
        for fact in record.facts:
            if fact.key not in COMPARE_KEYS:
                continue
            row = subjects.setdefault(fact.key, SupplierRow(subject=fact.key))
            row.values.append(
                {
                    "source_id": record.source_id,
                    "citation": label_of.get(record.source_id, "[S?]"),
                    "value": fact.value,
                    "kind": fact.kind,
                    "note": fact.note or "",
                }
            )
    for key in sorted(subjects):
        row = subjects[key]
        distinct: list[str] = []
        for entry in row.values:
            if not any(_same_value(entry["value"], d) for d in distinct):
                distinct.append(entry["value"])
        row.conflict = len(distinct) > 1
        if row.conflict:
            result.conflicts.append(
                {
                    "subject": key,
                    "detail": (
                        f"{len(distinct)} differing values for '{key}' across "
                        f"{len(row.values)} sources"
                    ),
                    "values": row.values,
                }
            )
        result.rows.append(row)

    present = set(subjects)
    for key in required_keys or []:
        if key not in present:
            result.gaps.append(key)

    estimate_keys = sorted(
        {row.subject for row in result.rows if any(v["kind"] == "estimate" for v in row.values)}
    )
    if estimate_keys:
        result.disclosures.append(
            f"figures for {', '.join(estimate_keys)} are asking/quotation snapshots "
            "(estimates), not verified costs"
        )
    return result


__all__ = ["COMPARE_KEYS", "SupplierComparison", "SupplierRow", "compare_suppliers"]
