"""Search and page-fetch providers (phase 7 deliverables #1-#2).

Two transports, one honest contract:

- ``canned`` (default): deterministic providers served from the committed
  research evaluation corpus. Every result discloses its mode — canned output
  is clearly labeled offline data, never dressed up as live web results.
- ``http`` (fetch only): real page retrieval through the FetchPolicy wall
  (scheme/port/userinfo/localhost checks, per-hop redirect re-checks,
  resolve-then-verify DNS, global-routability requirement, size and
  content-type caps).

A live *search* provider needs a third-party search API key; none is
configured, so search is canned-only for now and says so verbatim.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from xp_core.logging import get_logger

from research_adapter.extract import ExtractedPage, extract_html, extract_plain_text
from research_adapter.policy import FetchPolicy

log = get_logger(__name__)

MAX_REDIRECTS = 3
USER_AGENT = "XP-Research-Agent/0.1 (research tool; fetched pages are untrusted data)"


# -- shared shapes ----------------------------------------------------------------


@dataclass
class SearchListing:
    url: str
    title: str
    snippet: str


@dataclass
class SearchOutcome:
    mode: str  # canned | http
    results: list[SearchListing] = field(default_factory=list)
    disclosure: str = ""


@dataclass
class FetchOutcome:
    status: str  # ok | unavailable | denied | error
    mode: str  # canned | http
    url: str
    http_status: int | None = None
    content_type: str | None = None
    page: ExtractedPage | None = None
    is_listing_snapshot: bool = False
    reason: str = ""


# -- search ------------------------------------------------------------------------


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 5) -> SearchOutcome: ...


class CannedSearchProvider:
    """Deterministic keyword search over the evaluation corpus.

    Matching is honest: token intersection against entry keywords, results in
    stable (score, corpus-order) order, and an explicit canned-mode
    disclosure on every outcome. No entry matches -> zero results plus the
    disclosure, never filler.
    """

    def __init__(self, corpus: list[dict[str, Any]]) -> None:
        self.corpus = corpus

    async def search(self, query: str, limit: int = 5) -> SearchOutcome:
        tokens = {t for t in query.lower().split() if len(t) > 2}
        scored: list[tuple[int, int, SearchListing]] = []
        for idx, entry in enumerate(self.corpus):
            keywords = {str(k).lower() for k in entry.get("keywords", [])}
            overlap = len(tokens & keywords)
            if overlap <= 0:
                continue
            scored.append(
                (
                    -overlap,
                    idx,
                    SearchListing(
                        url=str(entry["url"]),
                        title=str(entry.get("title", "")),
                        snippet=str(entry.get("snippet", ""))[:300],
                    ),
                )
            )
        scored.sort(key=lambda t: (t[0], t[1]))
        return SearchOutcome(
            mode="canned",
            results=[s[2] for s in scored[: max(1, limit)]],
            disclosure=(
                "search runs in canned mode over the committed offline evaluation "
                "corpus — results are fixed research fixtures, not live web listings"
            ),
        )


# -- fetch -------------------------------------------------------------------------


class FetchProvider(Protocol):
    async def fetch(self, url: str) -> FetchOutcome: ...


class CannedFetchProvider:
    """Serves corpus pages by exact URL, byte-identical every time.

    A URL absent from the corpus returns status=unavailable — the honest
    canned equivalent of a dead page, which the eval set uses to prove that
    unavailable sources are disclosed.
    """

    def __init__(self, corpus: list[dict[str, Any]]) -> None:
        self.by_url = {str(e["url"]): e for e in corpus}

    async def fetch(self, url: str) -> FetchOutcome:
        entry = self.by_url.get(url)
        if entry is None:
            return FetchOutcome(
                status="unavailable",
                mode="canned",
                url=url,
                reason="page is not in the offline evaluation corpus (canned mode)",
            )
        data = str(entry.get("text", "")).encode("utf-8")
        page = extract_html(data, base_title=str(entry.get("title", "")))
        return FetchOutcome(
            status="ok",
            mode="canned",
            url=url,
            http_status=200,
            content_type="text/html",
            page=page,
            is_listing_snapshot=bool(entry.get("is_listing", False)),
        )


class HttpFetchProvider:
    """Real permitted-page retrieval behind the FetchPolicy wall.

    Defense order per request: policy.check_url -> DNS resolve (in a thread,
    via the injectable ``resolver``) -> policy.check_resolved on EVERY
    address -> request with redirects followed MANUALLY so each hop re-passes
    the full wall -> content-type + size caps -> extraction.
    """

    def __init__(
        self,
        policy: FetchPolicy | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Any = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.policy = policy or FetchPolicy()
        self._client = client
        self._resolver = resolver or _default_resolver
        self.timeout_seconds = timeout_seconds

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/json"},
            )
        return self._client

    async def fetch(self, url: str) -> FetchOutcome:
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            verdict = self.policy.check_url(current)
            if not verdict.allowed:
                return FetchOutcome(status="denied", mode="http", url=url, reason=verdict.reason)
            parsed = httpx.URL(current)
            try:
                addresses = await self._resolve(parsed.host)
            except OSError as exc:
                return FetchOutcome(
                    status="unavailable", mode="http", url=url, reason=f"DNS resolution failed: {exc}"
                )
            verdict = self.policy.check_resolved(parsed.host, addresses)
            if not verdict.allowed:
                return FetchOutcome(status="denied", mode="http", url=url, reason=verdict.reason)
            try:
                return await self._request_once(url, current)
            except _Redirect as redir:
                current = str(redir.location)
                continue
            except httpx.HTTPStatusError as exc:
                return FetchOutcome(
                    status="unavailable",
                    mode="http",
                    url=url,
                    http_status=exc.response.status_code,
                    reason=f"upstream returned HTTP {exc.response.status_code}",
                )
            except httpx.HTTPError as exc:
                return FetchOutcome(status="error", mode="http", url=url, reason=f"fetch failed: {exc}")
        return FetchOutcome(
            status="denied", mode="http", url=url, reason=f"more than {MAX_REDIRECTS} redirects"
        )

    async def _resolve(self, host: str) -> list[str]:
        import asyncio

        loop = asyncio.get_running_loop()
        infos = await loop.run_in_executor(None, self._resolver, host)
        return [i[4][0] for i in infos]

    async def _request_once(self, original_url: str, url: str) -> FetchOutcome:
        """One hop; redirects are raised back to fetch() so every hop re-passes
        the full permission wall (scheme, DNS, resolved IPs)."""
        client = self._ensure_client()
        async with client.stream("GET", url, follow_redirects=False) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                if not location:
                    return FetchOutcome(
                        status="error", mode="http", url=original_url,
                        reason=f"redirect {resp.status_code} without a Location header",
                    )
                raise _Redirect(httpx.URL(resp.url).join(location))
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            verdict = self.policy.check_content_type(content_type)
            if not verdict.allowed:
                return FetchOutcome(
                    status="denied", mode="http", url=original_url,
                    http_status=resp.status_code, content_type=content_type, reason=verdict.reason,
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes(16_384):
                size += len(chunk)
                if size > self.policy.max_bytes:
                    return FetchOutcome(
                        status="denied", mode="http", url=original_url,
                        http_status=resp.status_code, content_type=content_type,
                        reason=f"body exceeds the {self.policy.max_bytes}-byte limit",
                    )
                chunks.append(chunk)
            data = b"".join(chunks)
            base = extract_plain_text(data) if content_type.startswith("text/plain") or "json" in content_type else extract_html(data)
            return FetchOutcome(
                status="ok",
                mode="http",
                url=str(resp.url),
                http_status=resp.status_code,
                content_type=content_type,
                page=base,
            )


class _Redirect(Exception):
    def __init__(self, location: httpx.URL) -> None:
        self.location = location


def _default_resolver(host: str) -> list[Any]:
    return socket.getaddrinfo(host, None)


def make_search_provider(mode: str, corpus: list[dict[str, Any]]) -> SearchProvider:
    if mode != "canned":
        raise ValueError(
            f"search mode {mode!r} is not available: no live search provider is "
            "configured (a search API key would be required); use 'canned'"
        )
    return CannedSearchProvider(corpus)


def make_fetch_provider(
    mode: str, corpus: list[dict[str, Any]], *, policy: FetchPolicy | None = None, **kwargs: Any
) -> FetchProvider:
    if mode == "canned":
        return CannedFetchProvider(corpus)
    if mode == "http":
        return HttpFetchProvider(policy=policy, **kwargs)
    raise ValueError(f"fetch mode {mode!r} must be 'canned' or 'http'")


__all__ = [
    "CannedFetchProvider",
    "CannedSearchProvider",
    "FetchOutcome",
    "FetchProvider",
    "HttpFetchProvider",
    "SearchListing",
    "SearchOutcome",
    "SearchProvider",
    "make_fetch_provider",
    "make_search_provider",
]
