"""Source freshness and confidence indicators (phase-8 deliverable #7).

Two pure, deterministic indicators attached to every source wherever it is
shown (result endpoint, comparison rows, report appendix):

- freshness: how old the retrieval snapshot is relative to a reference time.
  fresh (<24h) / recent (<7d) / stale (<30d) / outdated (>=30d) / unknown.
- confidence: how much the record's facts can be trusted as evidence, from
  status, retrieval mode, and cross-source agreement - capped below 1.0
  because nothing here verifies truth, only provenance quality. Canned
  fixtures are honestly marked synthetic-for-the-world in the rationale.

Neither indicator is ever derived from page content claims (a page saying
"trusted!" changes nothing) - only from the platform's own retrieval facts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from research_adapter.provenance import SourceRecord

FRESHNESS_ORDER = ("fresh", "recent", "stale", "outdated", "unknown")

# status -> base trust (0..1)
_STATUS_BASE = {"ok": 0.7, "listed": 0.2, "unavailable": 0.0, "denied": 0.0, "error": 0.0}
# retrieval mode -> bonus: http content was really retrieved from the world;
# canned content is a committed fixture - deterministic, but synthetic.
_MODE_BONUS = {"http": 0.2, "canned": 0.1}
# cross-source agreement bonus (compare_sources found the same value elsewhere)
_AGREEMENT_BONUS = 0.1
# nothing in this platform verifies factual truth - confidence never hits 1.0
_CONFIDENCE_CAP = 0.9


def freshness_label(retrieved_at: datetime | None, now: datetime | None = None) -> str:
    """Age of a retrieval snapshot against a reference time (default now).

    Deterministic: pass ``now`` explicitly in evals to keep verdicts stable.
    """
    if retrieved_at is None:
        return "unknown"
    reference = now or datetime.now(UTC)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    age_hours = (reference - retrieved_at).total_seconds() / 3600
    if age_hours < 0:  # future retrieval = clock skew; treat as fresh, never negative
        return "fresh"
    if age_hours < 24:
        return "fresh"
    if age_hours < 24 * 7:
        return "recent"
    if age_hours < 24 * 30:
        return "stale"
    return "outdated"


FRESHNESS_SCORE = {"fresh": 1.0, "recent": 0.66, "stale": 0.33, "outdated": 0.0, "unknown": 0.0}


def confidence_label(
    record: SourceRecord,
    *,
    agrees_with_other_sources: bool = False,
    now: datetime | None = None,
) -> tuple[str, str, float]:
    """(label, rationale, score) for one source record.

    Composition is fully visible in the rationale so the label is auditable
    rather than a magic number.
    """
    base = _STATUS_BASE.get(record.status, 0.0)
    parts = [f"status {record.status} -> {base:.2f}"]
    score = base
    bonus = _MODE_BONUS.get(record.retrieval_mode, 0.0)
    if record.status == "ok" and bonus:
        score += bonus
        parts.append(f"{record.retrieval_mode} retrieval -> +{bonus:.2f}")
    if agrees_with_other_sources and record.status == "ok":
        score += _AGREEMENT_BONUS
        parts.append(f"corroborated by another source -> +{_AGREEMENT_BONUS:.2f}")
    score = min(score, _CONFIDENCE_CAP)
    if record.retrieval_mode == "canned" and record.status == "ok":
        parts.append("canned fixture: deterministic offline data, synthetic for the world")
    if record.status in {"unavailable", "denied", "error"}:
        parts.append(record.note or "no reason recorded")
    label = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
    rationale = "; ".join(parts)
    return label, rationale, round(score, 2)


__all__ = [
    "FRESHNESS_ORDER",
    "FRESHNESS_SCORE",
    "confidence_label",
    "freshness_label",
]
