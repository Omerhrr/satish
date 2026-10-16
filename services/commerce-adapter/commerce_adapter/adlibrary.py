"""Supported ad-library integration (phase-8 deliverable #2, acceptance #1
and #3).

Honesty contract, enforced structurally:

- CANNED ONLY. There is no permitted live ad-library API configured, so the
  integration serves the committed offline fixture corpus and says so
  verbatim on every result. Only accessible, permitted sources are ever
  represented as searched (acceptance #1) - a query that matches no fixture
  returns zero results plus the disclosure, never filler.
- NO PERFORMANCE METRICS. Ad attributes (advertiser, platform, dates,
  regions, creative text) are summarized from the page's own facts. If a
  page literally prints performance metrics (CTR, impressions, reach...),
  those stay in provenance as untrusted page facts but are EXCLUDED from
  every summary and score, with an explicit disclosure (acceptance #3).
- Every listing is persisted as provenance by the API handler; this module
  stays pure so the eval runner and the registry share one code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research_adapter.provenance import Fact

from commerce_adapter.classify import PERFORMANCE_KEYS

# Ad attributes eligible for summary (everything else stays provenance-only)
AD_ATTRIBUTE_KEYS = {
    "advertiser",
    "ad_id",
    "platform",
    "first_seen",
    "last_seen",
    "regions",
    "creative",
}

CANNED_DISCLOSURE = (
    "ad-library integration runs in canned mode over the committed offline "
    "fixture corpus - no live or private ad library is accessed, and only "
    "these permitted fixtures are represented as searched"
)

NO_PERFORMANCE_DISCLOSURE = (
    "ad performance metrics are not collected, verified, or summarized by "
    "this integration; any performance numbers in page text are recorded as "
    "untrusted provenance only"
)


@dataclass
class AdLibraryOutcome:
    mode: str  # always "canned" today
    query: str
    ads: list[dict[str, Any]] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)


class CannedAdLibraryProvider:
    """Deterministic keyword search over the fixture corpus's ad-library
    entries. Zero matches are honest zero matches."""

    def __init__(self, corpus: list[dict[str, Any]]) -> None:
        self.corpus = [e for e in corpus if str(e.get("source_type", "")) == "ad_library"]

    async def search(self, query: str, limit: int = 5) -> AdLibraryOutcome:
        tokens = {t for t in query.lower().split() if len(t) > 2}
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, entry in enumerate(self.corpus):
            keywords = {str(k).lower() for k in entry.get("keywords", [])}
            overlap = len(tokens & keywords)
            if overlap <= 0:
                continue
            scored.append((-overlap, idx, entry))
        scored.sort(key=lambda t: (t[0], t[1]))

        ads: list[dict[str, Any]] = []
        disclosures: list[str] = [CANNED_DISCLOSURE]
        for _score, _idx, entry in scored[: max(1, limit)]:
            ads.append(
                {
                    "url": str(entry["url"]),
                    "title": str(entry.get("title", "")),
                }
            )
        if not ads:
            disclosures.append(
                "no fixture matched the query: zero results is the honest answer, "
                "not a silent empty page"
            )
        return AdLibraryOutcome(
            mode="canned", query=query, ads=ads, disclosures=disclosures
        )


def summarize_ad(facts: list[Fact]) -> tuple[dict[str, str], list[str]]:
    """(attributes, disclosures) for one fetched ad-library page.

    Only AD_ATTRIBUTE_KEYS enter the summary; performance keys trigger the
    no-performance disclosure and are excluded from the summary.
    """
    attributes: dict[str, str] = {}
    disclosures: list[str] = []
    for fact in facts:
        if fact.key in AD_ATTRIBUTE_KEYS:
            attributes[fact.key] = fact.value
    leaked = sorted({f.key for f in facts if f.key in PERFORMANCE_KEYS})
    if leaked:
        disclosures.append(
            "the page text also mentions performance metric(s) "
            f"({', '.join(leaked)}); they are kept as untrusted provenance and "
            "excluded from this summary - no ad-performance claim is made"
        )
    return attributes, disclosures


__all__ = [
    "AD_ATTRIBUTE_KEYS",
    "CANNED_DISCLOSURE",
    "NO_PERFORMANCE_DISCLOSURE",
    "AdLibraryOutcome",
    "CannedAdLibraryProvider",
    "summarize_ad",
]
