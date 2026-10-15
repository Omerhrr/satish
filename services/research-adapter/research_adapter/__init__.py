"""Research tools adapter (phase 7).

Providers, permission policy, extraction, provenance, and the cross-source
comparison workflow behind one package boundary, so the API/agent layers
never touch the network directly.

Live status, stated honestly:
- search: canned-only (a live provider needs a search API key — none configured)
- fetch:  canned (offline corpus) or http (real retrieval behind FetchPolicy)
"""

from research_adapter.compare import (
    ComparisonResult,
    Conflict,
    SubjectRow,
    compare_sources,
)
from research_adapter.extract import (
    ExtractedFact,
    ExtractedPage,
    extract_html,
    extract_plain_text,
)
from research_adapter.policy import FetchPolicy, PermissionVerdict
from research_adapter.provenance import (
    Fact,
    SourceRecord,
    citations_in,
    facts_from_extraction,
    unavailable_record,
)
from research_adapter.providers import (
    CannedFetchProvider,
    CannedSearchProvider,
    FetchOutcome,
    FetchProvider,
    HttpFetchProvider,
    SearchListing,
    SearchOutcome,
    SearchProvider,
    make_fetch_provider,
    make_search_provider,
)

__all__ = [
    "CannedFetchProvider",
    "CannedSearchProvider",
    "ComparisonResult",
    "Conflict",
    "ExtractedFact",
    "ExtractedPage",
    "Fact",
    "FetchOutcome",
    "FetchPolicy",
    "FetchProvider",
    "HttpFetchProvider",
    "PermissionVerdict",
    "SearchListing",
    "SearchOutcome",
    "SearchProvider",
    "SourceRecord",
    "SubjectRow",
    "citations_in",
    "compare_sources",
    "extract_html",
    "extract_plain_text",
    "facts_from_extraction",
    "make_fetch_provider",
    "make_search_provider",
    "unavailable_record",
]
