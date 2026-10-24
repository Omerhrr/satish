"""Phase-7 research tools: permission policy, extraction, provenance,
comparison, documents, product registry, and the explicit task result.

The phase-7 acceptance bars, each with a named test:
1. Reports cite the sources used            -> test_report_claims_all_cited / eval set
2. Unavailable sources + uncertainty shown  -> test_fetch_unavailable_is_a_record / eval
3. Files validated + privately stored       -> test_artifact_validated_and_private
4. Explicit result, limitations, XP receipt -> test_task_result_contract
5. Repeatable research evaluation set       -> tests/test_research_eval.py
"""

from __future__ import annotations

import csv as csv_mod
import io
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from app.services import agent_service
from app.services.research_tools import build_product_registry, load_corpus
from dsh_adapter.tools import ScopeDenied
from research_adapter import (
    FetchPolicy,
    compare_sources,
    extract_html,
    facts_from_extraction,
)
from research_adapter.provenance import Fact, SourceRecord, unavailable_record
from research_adapter.providers import (
    CannedFetchProvider,
    CannedSearchProvider,
    HttpFetchProvider,
)
from sqlalchemy import select
from xp_core.models.entities import Artifact, ResearchSource, Task
from xp_core.services.documents import (
    DocumentQualityError,
    ReportClaim,
    ReportSource,
    ReportSpec,
    build_csv,
    build_xlsx,
    check_report_spec,
    render_report_pdf,
    validate_document,
)
from xp_core.services.storage import LocalStorage

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SET = REPO_ROOT / "tests" / "data" / "research_eval_set.json"


# fetch permission policy


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "http://user:pass@example.com/x",
        "http://example.com:8080/x",
        "http://localhost/x",
        "http://api.local/x",
        "http://127.0.0.1/x",
        "http://10.0.0.9/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "not a url at all",
    ],
)
def test_fetch_policy_denies_non_public_targets(url: str):
    verdict = FetchPolicy().check_url(url)
    assert not verdict.allowed, url


@pytest.mark.parametrize(
    "url",
    ["https://example.com/page", "http://example.com/page?q=1", "https://93.184.216.34/x"],
)
def test_fetch_policy_allows_public_http_urls(url: str):
    assert FetchPolicy().check_url(url).allowed, url


def test_fetch_policy_dns_layer_denies_private_resolution():
    policy = FetchPolicy()
    assert policy.check_resolved("rebind.test", ["93.184.216.34"]).allowed
    # One private answer among several is enough to deny (rebinding fails closed).
    verdict = policy.check_resolved("rebind.test", ["93.184.216.34", "192.168.1.4"])
    assert not verdict.allowed
    assert not policy.check_resolved("dead.test", []).allowed


def test_fetch_policy_content_type_and_size_caps():
    policy = FetchPolicy(max_bytes=100)
    assert policy.check_content_type("text/html; charset=utf-8").allowed
    assert policy.check_content_type("application/json").allowed
    assert not policy.check_content_type("application/octet-stream").allowed
    assert not policy.check_content_type("image/png").allowed


async def test_http_fetch_denies_and_fetches_without_live_network():
    """httpx MockTransport: the SSRF wall denies before any socket; a public
    page flows through extraction; a redirect hop re-passes the wall."""
    policy = FetchPolicy()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "evil.test" and request.url.path == "/rebind":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><head><title>OK</title></head><body><p>price: 100</p></body></html>",
        )

    # DNS answers "publicly" for every host; the redirect hop then re-checks
    # the resolved IP of the target and denies.
    provider = HttpFetchProvider(
        policy,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=lambda host: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    ok = await provider.fetch("https://fine.test/page")
    assert ok.status == "ok" and ok.page is not None
    assert ok.page.title == "OK"
    assert [(f.key, f.value) for f in ok.page.facts] == [("price", "100")]

    rebind = await provider.fetch("https://evil.test/rebind")
    assert rebind.status == "denied"
    assert "not globally routable" in rebind.reason


async def test_http_fetch_enforces_size_cap():
    handler = lambda request: httpx.Response(  # noqa: E731
        200, headers={"content-type": "text/plain"}, content=b"x" * 5000
    )
    provider = HttpFetchProvider(
        FetchPolicy(max_bytes=100),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        resolver=lambda host: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    outcome = await provider.fetch("https://big.test/blob")
    assert outcome.status == "denied"
    assert "byte limit" in outcome.reason


# extraction + provenance classification


def test_extraction_deterministic_title_facts_and_hash():
    html = (
        b"<html><head><title>Listing</title>"
        b"<meta name='description' content='A test listing'></head>"
        b"<body><script>ignore me</script><p>price: 1000</p><p>brand: Acme</p></body></html>"
    )
    page = extract_html(html)
    assert page.title == "Listing"
    keys = {f.key: f.value for f in page.facts}
    assert keys["price"] == "1000" and keys["brand"] == "Acme"
    assert keys["description"] == "A test listing"
    assert "ignore me" not in page.text
    again = extract_html(html)
    assert again.content_sha256 == page.content_sha256
    assert again.byte_size == len(html)


def test_price_facts_from_listing_snapshots_are_estimates():
    at = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    facts = facts_from_extraction(
        [("price", "1450000"), ("brand", "Growatt"), ("warranty", "5 years")],
        is_listing_snapshot=True,
        retrieved_at=at,
    )
    by_key = {f.key: f for f in facts}
    assert by_key["price"].kind == "estimate"
    assert "not a live quote" in (by_key["price"].note or "")
    assert by_key["brand"].kind == "observed"


# comparison workflow


def _rec(sid: str, url: str, facts: list[Fact], status: str = "ok") -> SourceRecord:
    return SourceRecord(source_id=sid, url=url, title=url, status=status, facts=facts)


def test_compare_flags_numeric_and_text_conflicts_with_citations():
    records = [
        _rec("a", "https://a.test/", [Fact(key="price", value="1,450,000"), Fact(key="brand", value="Growatt")]),
        _rec("b", "https://b.test/", [Fact(key="price", value="1395000"), Fact(key="brand", value="Growatt")]),
    ]
    result = compare_sources(records)
    subjects = {r.subject: r for r in result.rows}
    assert subjects["brand"].conflict is False  # 1,450,000 vs 1395000 -> numeric compare
    assert subjects["price"].conflict is True
    citations = {v["citation"] for v in subjects["price"].values}
    assert citations == {"[S1]", "[S2]"}


def test_compare_discloses_gaps_and_unreachable_sources():
    records = [
        _rec("a", "https://a.test/", [Fact(key="price", value="100")]),
        unavailable_record("b", "https://b.test/", "unavailable", "dead page"),
        _rec("c", "https://c.test/", [], status="listed"),
    ]
    result = compare_sources(records, required_keys=["price", "warranty"])
    assert "warranty" in result.gaps and "price" not in result.gaps
    joined = " | ".join(result.disclosures)
    assert "https://b.test/" in joined and "unavailable" in joined
    assert "listed" in joined and "never fetched" in joined


# documents: quality gates, renderers, validation


def _spec(claims: list[ReportClaim], sources: list[ReportSource]) -> ReportSpec:
    return ReportSpec(
        title="t",
        goal="g",
        generated_at=datetime.now(UTC),
        claims=claims,
        sources=sources,
        limitations=["limit"],
        task_id="task-1",
    )


def test_report_quality_gate_refuses_uncited_claims():
    sources = [ReportSource(index=1, url="https://a.test/", title="A", status="ok")]
    good = _spec([ReportClaim(text="price: 100", citations=[1])], sources)
    assert check_report_spec(good) == []
    uncited = _spec([ReportClaim(text="price: 100", citations=[])], sources)
    violations = check_report_spec(uncited)
    assert any("not cited" in v for v in violations)
    unknown = _spec([ReportClaim(text="x", citations=[7])], sources)
    assert any("unknown source S7" in v for v in check_report_spec(unknown))
    with pytest.raises(DocumentQualityError):
        render_report_pdf(unknown)


def test_rendered_report_pdf_is_cited_and_valid():
    sources = [
        ReportSource(index=1, url="https://a.test/x", title="A", status="ok", fact_count=1),
        ReportSource(index=2, url="https://b.test/", title="B", status="listed"),
    ]
    spec = _spec([ReportClaim(text="price: 100", citations=[1])], sources)
    spec.conflicts = [{"subject": "price", "detail": "2 differing values"}]
    spec.gaps = ["warranty"]
    spec.unavailable = ["S3 https://c.test/ - unavailable: dead"]
    # The HTML is the honest textual surface for content assertions; WeasyPrint
    # compresses+encodes text as glyphs in the PDF, so byte-grepping PDFs is meaningless.
    from xp_core.services.documents import render_report_html

    html = render_report_html(spec)
    assert "https://a.test/x" in html
    assert "price: 100" in html and "warranty" in html
    pdf = render_report_pdf(spec)
    ok, detail = validate_document("pdf", pdf)
    assert ok, detail
    assert pdf[:5] == b"%PDF-"


def test_csv_and_xlsx_build_and_validate():
    headers = ["subject", "source", "value"]
    rows = [["price", "[S1]", "100"], ["brand", "[S2]", "Acme"]]
    csv_bytes = build_csv(headers, rows)
    ok, detail = validate_document("csv", csv_bytes)
    assert ok, detail

    parsed = list(csv_mod.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    assert parsed[0] == headers and parsed[1:] == rows

    xlsx_bytes = build_xlsx("comparison", headers, rows)
    ok, detail = validate_document("xlsx", xlsx_bytes)
    assert ok, detail
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(xlsx_bytes))
    assert wb.active.cell(row=2, column=1).value == "price"

    assert not validate_document("pdf", b"not a pdf")[0]
    assert not validate_document("csv", b"\xff\xfe garbage")[0]
    assert not validate_document("xlsx", b"PK\x03\x04 but not really a zip")[0]


# corpus + canned providers


def test_corpus_loads_from_eval_set(settings):
    settings.research_eval_set_path = str(EVAL_SET)
    corpus = load_corpus(settings)
    assert len(corpus) >= 4
    assert all("url" in e and "keywords" in e for e in corpus)


async def test_canned_search_and_fetch_are_deterministic_and_honest(settings):
    settings.research_eval_set_path = str(EVAL_SET)
    corpus = load_corpus(settings)
    search = CannedSearchProvider(corpus)
    fetch = CannedFetchProvider(corpus)

    first = await search.search("solar inverter 5kw price")
    second = await search.search("solar inverter 5kw price")
    assert [r.url for r in first.results] == [r.url for r in second.results]
    assert "canned mode" in first.disclosure

    miss = await search.search("zzz qqq nonexistent topic")
    assert miss.results == [] and "canned" in miss.disclosure

    ok = await fetch.fetch(corpus[0]["url"])
    assert ok.status == "ok" and ok.is_listing_snapshot is True
    missing = await fetch.fetch("https://shop.example.test/gone")
    assert missing.status == "unavailable" and "canned" in missing.reason


# product registry over the application DB


def _product_task(task_id: str, user_id: str) -> Task:
    return Task(id=task_id, user_id=user_id, objective="solar inverter 5kw price", status="running", budget_xp=50)


async def test_registry_tools_persist_provenance_and_artifacts(session, dev_user, settings):
    settings.research_eval_set_path = str(EVAL_SET)
    task = _product_task("task-research-1", dev_user.id)
    session.add(task)
    await session.commit()
    storage = LocalStorage(settings.artifact_dir)
    registry = build_product_registry(session=session, task=task, settings=settings, storage=storage)

    search = await registry.execute("web.search", {"query": "solar inverter 5kw price", "limit": 5}, {"research:read"})
    assert search["status"] == "ok" and search["results"], search
    listed_urls = {r["url"] for r in search["results"]}

    fetch = await registry.execute(
        "web.fetch_page", {"url": "https://shop.example.test/solar/inverter-5kw"}, {"research:read"}
    )
    assert fetch["status"] == "ok"
    assert fetch["fact_keys"][0] == "brand" or "price" in fetch["fact_keys"]
    assert "untrusted" in fetch["disclosure"]

    rows = (await session.execute(select(ResearchSource).where(ResearchSource.task_id == task.id))).scalars().all()
    statuses = {r.url: r.status for r in rows}
    assert all(url in statuses for url in listed_urls)
    assert statuses["https://shop.example.test/solar/inverter-5kw"] == "ok"

    # refetching the same URL upgrades, never duplicates
    await registry.execute("web.fetch_page", {"url": "https://shop.example.test/solar/inverter-5kw"}, {"research:read"})
    count = (
        await session.execute(
            select(ResearchSource).where(
                ResearchSource.task_id == task.id,
                ResearchSource.url == "https://shop.example.test/solar/inverter-5kw",
            )
        )
    ).scalars().all()
    assert len(count) == 1

    compare = await registry.execute("research.compare", {"required_keys": ["price"]}, {"research:read"})
    assert compare["status"] == "ok"

    pdf = await registry.execute(
        "docs.generate_pdf", {"title": "Solar inverter price research"}, {"documents:write"}
    )
    assert pdf["status"] == "ok" and pdf["cited_claims"] >= 1, pdf
    artifact = (
        await session.execute(select(Artifact).where(Artifact.id == pdf["artifact_id"]))
    ).scalars().one()
    assert artifact.status == "ready"
    assert artifact.task_id == task.id
    stored = storage.open_path(artifact.object_key).read_bytes()
    assert stored.startswith(b"%PDF-")

    csv_out = await registry.execute("docs.generate_csv", {"title": "comparison"}, {"documents:write"})
    assert csv_out["status"] == "ok"
    xlsx_out = await registry.execute("docs.generate_xlsx", {"title": "comparison"}, {"documents:write"})
    assert xlsx_out["status"] == "ok"

    # scope wall: documents without the scope are structurally unreachable
    with pytest.raises(ScopeDenied):
        await registry.execute("docs.generate_csv", {"title": "x"}, {"research:read"})


async def test_registry_quality_gate_refuses_to_render_uncited(session, dev_user, settings, monkeypatch):
    """No sources -> no claims -> the honest empty report; but a corrupted
    spec (a claim without a citation) must refuse rather than render."""
    settings.research_eval_set_path = str(EVAL_SET)
    task = _product_task("task-research-2", dev_user.id)
    session.add(task)
    await session.commit()
    registry = build_product_registry(
        session=session, task=task, settings=settings, storage=LocalStorage(settings.artifact_dir)
    )
    # Zero sources: the gate passes (no claims exist) and the report discloses that.
    empty = await registry.execute("docs.generate_pdf", {"title": "Nothing"}, {"documents:write"})
    assert empty["status"] == "ok" and empty["cited_claims"] == 0

    from app.services import research_tools as rt

    real_spec = rt._build_report_spec

    async def poisoned(*args, **kwargs):
        from xp_core.services.documents import ReportClaim

        spec, records = await real_spec(*args, **kwargs)
        spec.sources = []
        spec.claims = [ReportClaim(text="fabricated without a source", citations=[1])]
        return spec, records

    monkeypatch.setattr(rt, "_build_report_spec", poisoned)
    refused = await registry.execute("docs.generate_pdf", {"title": "Bad"}, {"documents:write"})
    assert refused["status"] == "quality_gate_failed"
    assert any("S1" in v or "cited" in v for v in refused["violations"])


# explicit result + XP receipt (end-to-end through the runtime)


@pytest.fixture()
async def client(session, dev_user):
    """API client, same wiring as the agent-runtime tests."""
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class _Scripted:
    """Plan mirroring a real research run: search, fetch, compare, deliver."""

    def __init__(self, plan: dict) -> None:
        self.plan = plan

    async def complete(self, messages, tools=None):
        import json

        return {
            "content": json.dumps(self.plan),
            "tool_calls": [],
            "finish_reason": "stop",
            "model": "stub",
            "revision_id": "stub",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "estimated_cost_usd": 0.0},
        }


async def test_task_result_contract(client, session, dev_user, monkeypatch):
    from xp_core.services import ledger

    await ledger.credit_purchase(session, user_id=dev_user.id, amount=100, payment_intent_id="seed-100")
    await session.commit()

    goal = "solar inverter 5kw price"
    monkeypatch.setattr(
        agent_service,
        "make_chat_client",
        lambda s: _Scripted(
            {
                "plan": [
                    {"step": 1, "tool": "web.search", "why": "collect", "arguments": {"query": goal, "limit": 5}},
                    {
                        "step": 2,
                        "tool": "web.fetch_page",
                        "why": "read",
                        "arguments": {"url": "https://shop.example.test/solar/inverter-5kw"},
                    },
                    {
                        "step": 3,
                        "tool": "web.fetch_page",
                        "why": "missing",
                        "arguments": {"url": "https://guides.energypedia.test/missing-page"},
                    },
                    {"step": 4, "tool": "research.compare", "why": "verify", "arguments": {"required_keys": ["price", "warranty"]}},
                    {
                        "step": 5,
                        "tool": "docs.generate_pdf",
                        "why": "deliver",
                        "arguments": {"title": "Solar inverter price research"},
                    },
                ],
                "estimated_xp": 22,
                "deliverable": f"Report: {goal}",
            }
        ),
    )

    task = (
        await client.post("/api/v1/tasks", json={"objective": goal, "budget_xp": 50})
    ).json()
    resp = await client.post(f"/api/v1/tasks/{task['id']}/run")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "completed"
    # search 5 + fetch 2 + fetch 2 + compare 3 + pdf 10 = 22
    assert body["actual_xp"] == 22

    result = (await client.get(f"/api/v1/tasks/{task['id']}/result")).json()

    # explicit result + artifacts
    assert result["deliverable"] == f"Report: {goal}"
    assert result["artifacts"], "the PDF artifact must be attached"
    art = result["artifacts"][0]
    assert art["content_type"] == "application/pdf" and art["download_url"].startswith("/api/v1/artifacts/")

    # provenance + disclosures (acceptance #2)
    statuses = {s["url"]: s["status"] for s in result["sources"]}
    assert statuses["https://shop.example.test/solar/inverter-5kw"] == "ok"
    assert statuses["https://guides.energypedia.test/missing-page"] == "unavailable"
    # the fetched listing DOES carry 'warranty: 5 years', so no gap is reported
    assert result["gaps"] == []
    joined = " ".join(result["limitations"])
    assert "missing-page" in joined and "unavailable" in joined

    # XP receipt (acceptance #4): budget 50, actual 22, released 28
    receipt = result["xp_receipt"]
    assert receipt["status"] == "settled"
    assert receipt["budget_xp"] == 50 and receipt["actual_xp"] == 22
    assert receipt["released_xp"] == 28
    assert receipt["charge_entry_id"] and receipt["settled_at"] is not None

    balance = (await client.get("/api/v1/xp/balance")).json()["balance_xp"]
    assert balance == 100 - 22

    # artifact download is owner-checked (private by default)
    dl = await client.get(art["download_url"])
    assert dl.status_code == 200 and dl.content[:5] == b"%PDF-"


async def test_result_endpoint_receipt_states(session, dev_user):
    """Pending, failed, and cancelled tasks report honest receipt states."""
    from app.main import app
    from httpx import ASGITransport, AsyncClient
    from xp_core.services import ledger

    await ledger.credit_purchase(session, user_id=dev_user.id, amount=50, payment_intent_id="seed-50")
    await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = (
            await client.post("/api/v1/tasks", json={"objective": "receipt state check", "budget_xp": 10})
        ).json()
        pending = (await client.get(f"/api/v1/tasks/{task['id']}/result")).json()
        assert pending["xp_receipt"]["status"] == "pending_settlement"

        cancel = await client.post(f"/api/v1/tasks/{task['id']}/cancel")
        assert cancel.status_code == 200
        cancelled = (await client.get(f"/api/v1/tasks/{task['id']}/result")).json()
        assert cancelled["xp_receipt"]["status"] == "no_charge"
        assert cancelled["xp_receipt"]["released_xp"] == 10


# untrusted wrapping is still the adapter's contract
def test_untrusted_wrapper_contract():
    from dsh_adapter.client import UNTRUSTED_CLOSE, UNTRUSTED_OPEN, wrap_untrusted

    wrapped = wrap_untrusted("<script>steal</script>")
    assert wrapped.startswith(UNTRUSTED_OPEN) and wrapped.endswith(UNTRUSTED_CLOSE)


async def test_brave_search_provider_parses_and_fails_honestly():
    import httpx
    from research_adapter.providers import BraveSearchProvider, make_search_provider

    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Subscription-Token")
        seen["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Solar <strong>inverter</strong> prices", "url": "https://example.ng/inverters", "description": "Compare &amp; save"},
            {"title": "bad", "url": "javascript:alert(1)", "description": "x"},
        ]}})

    p = BraveSearchProvider("key123", transport=httpx.MockTransport(ok))
    out = await p.search("solar inverter prices Nigeria", limit=5)
    assert seen == {"token": "key123", "q": "solar inverter prices Nigeria"}
    assert out.mode == "brave" and len(out.results) == 1
    assert out.results[0].title == "Solar inverter prices" and out.results[0].snippet == "Compare & save"

    down = BraveSearchProvider("k", transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    out = await down.search("x")
    assert out.results == [] and "429" in out.disclosure

    from research_adapter.providers import CannedSearchProvider
    assert type(make_search_provider("brave", [], api_key=None)).__name__ == "KeylessWebSearchProvider"  # live, keyless


async def test_keyless_web_search_parses_results_and_fails_honestly():
    import httpx
    from research_adapter.providers import KeylessWebSearchProvider

    page = (
        '<div><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.ng%2Frice&amp;rut=x">'
        'Rice <b>prices</b></a><a class="result__snippet" href="#">Bag of rice is &#8358;80,000</a></div>'
        '<div><a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x">Ad</a></div>'
        '<div><a class="result__a" href="https://second.example.com/a">Second</a></div>'
    )

    def ok(request):
        return httpx.Response(200, text=page)

    out = await KeylessWebSearchProvider(transport=httpx.MockTransport(ok)).search("rice price", 5)
    assert [r.url for r in out.results] == ["https://example.ng/rice", "https://second.example.com/a"]
    assert out.results[0].title == "Rice prices" and "80,000" in out.results[0].snippet
    assert out.mode == "web"

    bad = await KeylessWebSearchProvider(transport=httpx.MockTransport(lambda r: httpx.Response(503))).search("x")
    assert bad.results == [] and "503" in bad.disclosure
