"""Search and page-fetch providers (phase 7 deliverables #1-#2).

Two transports, one honest contract:

- ``canned`` (default): deterministic providers served from the committed
  research evaluation corpus. Every result discloses its mode - canned output
  is clearly labeled offline data, never dressed up as live web results.
- ``http`` (fetch only): real page retrieval through the FetchPolicy wall
  (scheme/port/userinfo/localhost checks, per-hop redirect re-checks,
  resolve-then-verify DNS, global-routability requirement, size and
  content-type caps).

- ``brave`` (search): live web search through the Brave Search API
  (independent index, free tier). Needs XP_BRAVE_SEARCH_API_KEY; pair it with
  fetch mode ``http`` so the agent can read the pages it finds.
"""

from __future__ import annotations

import html
import re
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


# shared shapes


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


# search


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
                "corpus - results are fixed research fixtures, not live web listings"
            ),
        )


BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_TAG = re.compile(r"<[^>]+>")


def _plain(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


class BraveSearchProvider:
    """Live web search via the Brave Search API.

    Results are listings only (title, URL, snippet); the agent still has to
    fetch each page through the FetchPolicy wall before citing it. Failures
    return zero results with an honest disclosure, never filler.
    """

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None, country: str = "") -> None:
        if not api_key:
            raise ValueError("brave search needs XP_BRAVE_SEARCH_API_KEY")
        self.api_key = api_key
        self.transport = transport
        self.country = country

    async def search(self, query: str, limit: int = 5) -> SearchOutcome:
        params: dict[str, Any] = {"q": query[:400], "count": max(1, min(limit, 20)), "safesearch": "moderate"}
        if self.country:
            params["country"] = self.country
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                resp = await client.get(BRAVE_ENDPOINT, params=params, headers=headers)
            if resp.status_code != 200:
                log.warning("brave_search_failed", status=resp.status_code)
                return SearchOutcome(mode="brave", disclosure=f"live search failed (HTTP {resp.status_code}); no results used")
            items = (resp.json().get("web") or {}).get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("brave_search_failed", error=str(exc))
            return SearchOutcome(mode="brave", disclosure="live search was unreachable; no results used")
        results = [
            SearchListing(url=str(i["url"]), title=_plain(i.get("title", "")), snippet=_plain(i.get("description", ""))[:300])
            for i in items
            if str(i.get("url", "")).startswith(("http://", "https://"))
        ][: max(1, limit)]
        return SearchOutcome(mode="brave", results=results, disclosure="live web search results from Brave Search")


DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)', re.S
)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _ddg_url(href: str) -> str:
    from urllib.parse import parse_qs, unquote, urlparse

    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    u = urlparse(href)
    if u.netloc.endswith("duckduckgo.com") and u.path.startswith("/l/"):
        target = parse_qs(u.query).get("uddg", [""])[0]
        return unquote(target)
    return href


class KeylessWebSearchProvider:
    """Live web search with no API key (DuckDuckGo's HTML results page).

    Used when no Brave key is set, so research works out of the box. Ads and
    tracking links are dropped; failures return zero results honestly.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, region: str = "") -> None:
        self.transport = transport
        self.region = region

    async def search(self, query: str, limit: int = 5) -> SearchOutcome:
        data = {"q": query[:400]}
        if self.region:
            data["kl"] = self.region
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SatishResearch/1.0)", "Accept": "text/html"}
        try:
            async with httpx.AsyncClient(timeout=12, transport=self.transport, follow_redirects=True) as client:
                resp = await client.post(DDG_ENDPOINT, data=data, headers=headers)
            if resp.status_code != 200:
                log.warning("web_search_failed", status=resp.status_code)
                return SearchOutcome(mode="web", disclosure=f"live search failed (HTTP {resp.status_code}); no results used")
            body = resp.text
        except httpx.HTTPError as exc:
            log.warning("web_search_failed", error=str(exc))
            return SearchOutcome(mode="web", disclosure="live search was unreachable; no results used")
        results: list[SearchListing] = []
        seen: set[str] = set()
        for href, title, rest in _DDG_RESULT.findall(body):
            url = _ddg_url(href)
            if not url.startswith(("http://", "https://")) or "duckduckgo.com" in url or url in seen:
                continue
            if "ad_domain" in href or "/y.js" in href:
                continue
            seen.add(url)
            m = _DDG_SNIPPET.search(rest)
            results.append(SearchListing(url=url, title=_plain(title), snippet=_plain(m.group(1) if m else "")[:300]))
            if len(results) >= max(1, limit):
                break
        return SearchOutcome(mode="web", results=results, disclosure="live web search results")


# fetch


class FetchProvider(Protocol):
    async def fetch(self, url: str) -> FetchOutcome: ...


class CannedFetchProvider:
    """Serves corpus pages by exact URL, byte-identical every time.

    A URL absent from the corpus returns status=unavailable - the honest
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


def make_search_provider(
    mode: str, corpus: list[dict[str, Any]], *, api_key: str | None = None, **kwargs: Any
) -> SearchProvider:
    if mode == "canned":
        return CannedSearchProvider(corpus)
    if mode in ("brave", "auto", "web"):
        if mode != "web" and api_key:
            return BraveSearchProvider(api_key, **kwargs)
        region = str(kwargs.pop("country", "") or "")
        return KeylessWebSearchProvider(region=f"{region.lower()}-en" if region else "", **kwargs)
    raise ValueError(f"search mode {mode!r} must be 'canned', 'auto', 'brave' or 'web'")


def make_fetch_provider(
    mode: str, corpus: list[dict[str, Any]], *, policy: FetchPolicy | None = None, **kwargs: Any
) -> FetchProvider:
    if mode == "canned":
        return CannedFetchProvider(corpus)
    if mode == "http":
        return HttpFetchProvider(policy=policy, **kwargs)
    raise ValueError(f"fetch mode {mode!r} must be 'canned' or 'http'")


__all__ = [
    "BraveSearchProvider",
    "CannedFetchProvider",
    "CannedSearchProvider",
    "FetchOutcome",
    "FetchProvider",
    "HttpFetchProvider",
    "KeylessWebSearchProvider",
    "SearchListing",
    "SearchOutcome",
    "SearchProvider",
    "make_fetch_provider",
    "make_search_provider",
]
