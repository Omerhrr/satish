"""Cross-source comparison workflow (phase 7 deliverable #4).

Takes the task's provenance records and produces a cited comparison:
- subjects: fact keys seen across sources, each row carrying every source's
  value WITH its citation index
- conflicts: same subject, different values - surfaced, never averaged away
- gaps: required keys no source provides (and keys individual sources omit)
- disclosures: estimate/staleness notes, unavailable/denied/errored sources

Deterministic and pure: same records -> same comparison, every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_adapter.provenance import SourceRecord


@dataclass
class SubjectRow:
    subject: str
    values: list[dict[str, str]] = field(default_factory=list)  # {source_id, citation, value, kind, note}
    conflict: bool = False


@dataclass
class Conflict:
    subject: str
    detail: str
    values: list[dict[str, str]]


@dataclass
class ComparisonResult:
    rows: list[SubjectRow] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)


_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def _numeric(value: str) -> float | None:
    match = _NUM.search(value.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _same_value(a: str, b: str) -> bool:
    """Values agree if equal textually, or numerically equal when both parse."""
    na, nb = _numeric(a), _numeric(b)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    return a.strip().casefold() == b.strip().casefold()


def compare_sources(
    records: list[SourceRecord], required_keys: list[str] | None = None
) -> ComparisonResult:
    """Compare fetched sources; cite every value with its [S{n}] label."""
    result = ComparisonResult()
    ordered = [r for r in records if r.status == "ok"]
    label_of = {r.source_id: f"[S{i}]" for i, r in enumerate(records, start=1)}

    # group fact values by subject (fact key)
    subjects: dict[str, SubjectRow] = {}
    for record in ordered:
        for fact in record.facts:
            row = subjects.setdefault(fact.key, SubjectRow(subject=fact.key))
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
                Conflict(
                    subject=key,
                    detail=(
                        f"{len(distinct)} differing values for '{key}' across "
                        f"{len(row.values)} sources"
                    ),
                    values=row.values,
                )
            )
        result.rows.append(row)

    # gaps: required keys no fetched source provides
    present = set(subjects)
    for key in required_keys or []:
        if key not in present:
            result.gaps.append(key)

    # disclosures: estimates and unreachable sources
    estimate_rows = [row for row in result.rows if any(v["kind"] == "estimate" for v in row.values)]
    if estimate_rows:
        names = ", ".join(sorted({row.subject for row in estimate_rows}))
        result.disclosures.append(
            f"figures for {names} are listing snapshots (estimates), not live quotes"
        )
    for record in records:
        if record.status in {"unavailable", "denied", "error"}:
            result.disclosures.append(
                f"source {label_of.get(record.source_id, '[S?]')} {record.url} is "
                f"{record.status}: {record.note or 'no reason recorded'}"
            )
        elif record.status == "listed":
            result.disclosures.append(
                f"source {label_of.get(record.source_id, '[S?]')} {record.url} was listed by "
                "search but never fetched - it contributes no facts"
            )
    return result


__all__ = ["ComparisonResult", "Conflict", "SubjectRow", "compare_sources"]
