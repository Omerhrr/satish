"""Source citation and provenance model (phase 7 deliverable #3).

Research quality rules implemented here (agent_and_tooling.research_quality):
- every source keeps url, retrieval time, title, and extracted facts
- facts are typed: observed | estimate | assumption - estimates are NEVER
  presented as live observations (e.g. a marketplace listing snapshot)
- citations are stable [S{n}] references resolved against the source list
- unavailable sources are first-class records, disclosed, never silently
  dropped
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

FactKind = Literal["observed", "estimate", "assumption"]

SOURCE_STATUSES = ("listed", "ok", "unavailable", "denied", "error")

_CITATION = re.compile(r"\[S(\d+)\]")

# Fact keys that mean "a price figure" - combined with a listing snapshot
# flag they are classified as estimates, never as live observed prices.
PRICE_KEYS = {"price", "asking_price", "listed_price", "unit_price", "current_price"}


@dataclass
class Fact:
    key: str
    value: str
    kind: FactKind = "observed"
    note: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"key": self.key, "value": self.value, "kind": self.kind, "note": self.note}

    @staticmethod
    def from_dict(raw: dict) -> Fact:
        return Fact(
            key=str(raw.get("key", "")),
            value=str(raw.get("value", "")),
            kind=raw.get("kind", "observed"),  # type: ignore[arg-type]
            note=raw.get("note"),
        )


@dataclass
class SourceRecord:
    """One source's provenance, as persisted in research_sources and used by
    the comparison workflow and the report builder."""

    source_id: str
    url: str
    title: str
    status: str  # listed | ok | unavailable | denied | error
    retrieved_at: datetime | None = None
    facts: list[Fact] = field(default_factory=list)
    content_sha256: str | None = None
    retrieval_mode: str = "canned"  # canned | http
    note: str | None = None

    def citation_label(self, records: list[SourceRecord]) -> str:
        """The [S{n}] label for this source within an ordered record list."""
        for i, rec in enumerate(records, start=1):
            if rec.source_id == self.source_id:
                return f"[S{i}]"
        return "[S?]"


def citations_in(text: str) -> list[int]:
    """Citation indices referenced by a claim/paragraph, e.g. 'x [S1] [S3]'."""
    return [int(m) for m in _CITATION.findall(text)]


# fact classification


def facts_from_extraction(
    extracted: list[tuple[str, str]],  # (key, value) pairs from the extractor
    *,
    is_listing_snapshot: bool,
    retrieved_at: datetime | None,
) -> list[Fact]:
    """Type extracted key/value pairs into provenance Facts.

    Deterministic rule: price-ish keys coming from a marketplace-style listing
    snapshot are ``estimate`` with an explicit staleness note; everything else
    is ``observed``. Nothing is ever invented here.
    """
    out: list[Fact] = []
    stamp = retrieved_at.strftime("%Y-%m-%d %H:%M UTC") if retrieved_at else "an unknown time"
    for key, value in extracted:
        if is_listing_snapshot and key in PRICE_KEYS:
            out.append(
                Fact(
                    key=key,
                    value=value,
                    kind="estimate",
                    note=f"listing snapshot retrieved at {stamp}, not a live quote",
                )
            )
        else:
            out.append(Fact(key=key, value=value, kind="observed"))
    return out


def unavailable_record(
    source_id: str, url: str, status: str, reason: str
) -> SourceRecord:
    """An unavailable/denied/errored source is a record, not a shrug."""
    return SourceRecord(
        source_id=source_id,
        url=url,
        title="",
        status=status,
        note=reason,
    )


__all__ = [
    "PRICE_KEYS",
    "SOURCE_STATUSES",
    "Fact",
    "FactKind",
    "SourceRecord",
    "citations_in",
    "facts_from_extraction",
    "unavailable_record",
]
