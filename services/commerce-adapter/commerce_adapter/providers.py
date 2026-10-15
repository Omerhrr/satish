"""Commerce fetch provider: the research canned fetch + source-type plumbing.

The commerce corpus entries carry a ``source_type`` (supplier | market |
auction | dealer | official | ad_library). The provider wraps the research
CannedFetchProvider (same permission-free fixture semantics, same honest
'unavailable' for URLs outside the corpus) and surfaces the entry's
source_type so facts can be commerce-classified and the comparison layer
can tell suppliers from listings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_adapter.extract import ExtractedPage
from research_adapter.providers import CannedFetchProvider


@dataclass
class CommerceFetchOutcome:
    status: str  # ok | unavailable | denied | error
    mode: str  # canned
    url: str
    source_type: str  # supplier | market | auction | dealer | official | ad_library | unknown
    page: ExtractedPage | None = None
    is_listing_snapshot: bool = False
    reason: str = ""


class CommerceFetchProvider:
    """Corpus fetch that keeps source_type alongside the research outcome."""

    def __init__(self, corpus: list[dict[str, Any]]) -> None:
        self._inner = CannedFetchProvider(corpus)
        self._by_url = {str(e["url"]): e for e in corpus}

    async def fetch(self, url: str) -> CommerceFetchOutcome:
        entry = self._by_url.get(url)
        source_type = str(entry.get("source_type", "unknown")) if entry else "unknown"
        outcome = await self._inner.fetch(url)
        if outcome.status != "ok" or outcome.page is None:
            return CommerceFetchOutcome(
                status=outcome.status,
                mode=outcome.mode,
                url=outcome.url,
                source_type=source_type,
                reason=outcome.reason,
            )
        return CommerceFetchOutcome(
            status="ok",
            mode=outcome.mode,
            url=outcome.url,
            source_type=source_type,
            page=outcome.page,
            is_listing_snapshot=outcome.is_listing_snapshot,
        )


__all__ = ["CommerceFetchOutcome", "CommerceFetchProvider"]
