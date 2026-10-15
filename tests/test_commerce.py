"""Phase-8 commerce intelligence: transparent scoring, supplier comparison,
vehicle checks, ad-library honesty, landed-cost template, freshness/confidence.

The phase-8 acceptance bars, each with named tests:
1. "Only accessible and permitted sources are represented as searched"
   -> test_ad_library_provider_honesty / test_commerce_registry_end_to_end
2. "The report distinguishes asking prices, estimates, and verified costs"
   -> test_landed_cost_template_types_lines / test_commerce_registry_end_to_end
   (asking = estimate, official rate = observed, user input = assumption,
   verified costs: none exist and the output says so)
3. "No unsupported demand, ad-performance, or availability claims are
   invented" -> test_scoring_never_invents_demand_or_performance /
   test_ad_library_summarize_excludes_performance
4. "Scoring factors are visible and configurable"
   -> test_scoring_deterministic_and_transparent /
   test_scoring_configurable_weights / test_scoring_config_fallback_disclosed
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.services import agent_service
from app.services.research_tools import build_product_registry
from commerce_adapter import (
    CANNED_DISCLOSURE,
    DEFAULT_FACTORS,
    CannedAdLibraryProvider,
    compute_landed_cost,
    confidence_label,
    freshness_label,
    parse_scoring_config,
    score_records,
    summarize_ad,
)
from commerce_adapter.landed import LandedCostError
from dsh_adapter.tools import ScopeDenied
from httpx import ASGITransport, AsyncClient
from research_adapter.provenance import SourceRecord
from sqlalchemy import select
from xp_core.models.entities import ResearchSource, Task, TaskEvent
from xp_core.services.documents import render_report_html
from xp_core.services.storage import LocalStorage


@pytest.fixture()
async def client(session, dev_user):
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMERCE_SET = REPO_ROOT / "tests" / "data" / "commerce_eval_set.json"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _corpus() -> list[dict]:
    return json.loads(COMMERCE_SET.read_text())["corpus"]


def _record(source_id: str, url: str, title: str, source_type: str, text_lines: list[tuple[str, str]]) -> SourceRecord:
    from commerce_adapter import commerce_facts

    facts = commerce_facts(text_lines, source_type=source_type, retrieved_at=NOW)
    return SourceRecord(
        source_id=source_id,
        url=url,
        title=title,
        status="ok",
        retrieved_at=NOW,
        facts=facts,
        retrieval_mode="canned",
        note=f"source_type={source_type}",
    )


def _supplier_a() -> SourceRecord:
    return _record(
        "sup-a", "https://supplier.example.test/energy/inverter-5kw-quote",
        "5kW Hybrid Inverter - Supplier A quotation", "supplier",
        [("product", "5kW hybrid inverter"), ("unit_price", "1450"), ("currency", "USD"),
         ("moq", "10"), ("lead_time_days", "21"), ("shipping_total", "380"),
         ("warranty_months", "24"), ("supplier", "SunGrid Ltd")],
    )


def _supplier_b() -> SourceRecord:
    return _record(
        "sup-b", "https://supplier.example.test/energy/inverter-5kw-quote-b",
        "5kW Hybrid Inverter - Supplier B quotation", "supplier",
        [("product", "5kW hybrid inverter"), ("unit_price", "1520"), ("currency", "USD"),
         ("moq", "5"), ("lead_time_days", "14"), ("shipping_total", "300"),
         ("warranty_months", "12"), ("supplier", "VoltTrade Ltd")],
    )


def _market_usd() -> SourceRecord:
    return _record(
        "mkt-usd", "https://market.example.test/lagos/inverters-5kw",
        "5kW hybrid inverter - Lagos market listing", "market",
        [("product", "5kW hybrid inverter"), ("asking_price", "1495"), ("currency", "USD"),
         ("seller", "Ikeja Power Store")],
    )


def _market_ghs() -> SourceRecord:
    return _record(
        "mkt-ghs", "https://market.example.test/accra/inverters",
        "5kW hybrid inverter - Accra market listing", "market",
        [("product", "5kW hybrid inverter"), ("asking_price", "9800"), ("currency", "GHS"),
         ("seller", "Accra Solar Mart"), ("stock_status", "in stock")],
    )


def _tariff() -> SourceRecord:
    return _record(
        "tariff", "https://tariff.example.test/ng/import-duty-solar",
        "Import duty schedule - solar equipment (published rate)", "official",
        [("category", "Solar inverter"), ("duty_rate_pct", "5"), ("levy_pct", "0"),
         ("authority", "Customs and Tariff Division")],
    )


# -- deliverable #7: freshness + confidence ---------------------------------------------


def test_freshness_labels_and_confidence():
    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    assert freshness_label(now - timedelta(hours=2), now) == "fresh"
    assert freshness_label(now - timedelta(hours=23), now) == "fresh"
    assert freshness_label(now - timedelta(days=3), now) == "recent"
    assert freshness_label(now - timedelta(days=29), now) == "stale"
    assert freshness_label(now - timedelta(days=31), now) == "outdated"
    assert freshness_label(None, now) == "unknown"

    ok_canned = SourceRecord(source_id="a", url="u", title="t", status="ok",
                             retrieved_at=now, retrieval_mode="canned")
    label, rationale, score = confidence_label(ok_canned)
    # provenance-quality trust: a deterministic fixture re-derives perfectly,
    # but the rationale says out loud that it is synthetic for the world
    assert label == "high" and "canned fixture" in rationale and score == pytest.approx(0.8)
    ok_http = SourceRecord(source_id="b", url="u", title="t", status="ok",
                           retrieved_at=now, retrieval_mode="http")
    label, rationale, score = confidence_label(ok_http)
    assert label == "high" and score == pytest.approx(0.9)
    listed = SourceRecord(source_id="c", url="u", title="t", status="listed",
                          retrieval_mode="canned")
    label, _r, score = confidence_label(listed)
    assert label == "low" and score == pytest.approx(0.2)
    # agreement bonus pushes corroborated ok+canned to 0.9; cap holds at 0.9
    label, _r, score = confidence_label(ok_canned, agrees_with_other_sources=True)
    assert score == pytest.approx(0.9)


# -- deliverable #3 / acceptance #4: transparent, configurable scoring ------------------


def test_scoring_deterministic_and_transparent():
    records = [_supplier_a(), _supplier_b(), _market_usd()]
    first = score_records(records, product="5kW hybrid inverter",
                          required_keys=["unit_price", "moq", "lead_time_days"], now=NOW)
    second = score_records(records, product="5kW hybrid inverter",
                           required_keys=["unit_price", "moq", "lead_time_days"], now=NOW)
    assert first.as_dict() == second.as_dict(), "same inputs -> same verdict"

    names = {f.name for f in first.factors}
    assert names == set(DEFAULT_FACTORS)
    for factor in first.factors:
        assert factor.weight == DEFAULT_FACTORS[factor.name]
        assert factor.signal, f"factor {factor.name} must show its raw signal"
    assert first.config_echo == DEFAULT_FACTORS, "weights echoed verbatim"
    # hand-computed expected score (defaults):
    # distinct 3/3=1.0; suppliers 2/2=1.0; spread (1520-1450)/1520=4.6% ->
    # 1-0.046.. /0.5 = 0.9079; freshness all fresh = 1.0; completeness 3/3 = 1.0
    spread_norm = 1 - ((1520 - 1450) / 1520) / 0.5
    expected = (2.0 * 1.0 + 1.5 * 1.0 + 1.5 * spread_norm + 1.0 * 1.0 + 1.0 * 1.0) / 7.0 * 100
    assert first.score == pytest.approx(expected, abs=0.1)
    assert any("demand" in d for d in first.disclosures), "the no-demand disclosure is mandatory"


def test_scoring_configurable_weights():
    records = [_supplier_a(), _supplier_b(), _market_usd()]
    base = score_records(records, product="5kW hybrid inverter",
                         required_keys=["unit_price", "moq", "lead_time_days"], now=NOW)
    # flatten price spread's weight to zero -> the score must move
    flat_weights = dict(DEFAULT_FACTORS, price_spread=0.0)
    flat = score_records(records, weights=flat_weights, product="5kW hybrid inverter",
                         required_keys=["unit_price", "moq", "lead_time_days"], now=NOW)
    assert flat.score != base.score
    assert flat.config_echo == flat_weights, "operator config echoed, not defaults"
    # a zero-weight factor still shows its signal (visibility) but contributes 0
    spread = next(f for f in flat.factors if f.name == "price_spread")
    assert spread.included and spread.weight == 0.0

    # config parsing: custom weights honored; defects fall back loudly
    weights, used_defaults, note = parse_scoring_config('{"price_spread": 3.0}')
    assert used_defaults is False and weights["price_spread"] == 3.0 and note == ""
    weights, used_defaults, note = parse_scoring_config("{not json")
    assert used_defaults is True and weights == DEFAULT_FACTORS and "invalid JSON" in note
    weights, used_defaults, note = parse_scoring_config('{"demand_score": 9}')
    assert used_defaults is True and "unknown" in note
    weights, used_defaults, note = parse_scoring_config('{"freshness": -1}')
    assert used_defaults is True and "non-negative" in note


def test_scoring_insufficient_data_excluded_not_zeroed():
    lone = score_records([_supplier_a()], product="5kW hybrid inverter",
                         required_keys=["unit_price", "moq"], now=NOW)
    spread = next(f for f in lone.factors if f.name == "price_spread")
    assert not spread.included and "one data point" in spread.reason
    assert "price_spread" in lone.excluded
    # score = weighted mean over INCLUDED factors only
    included = [f for f in lone.factors if f.included and f.normalized is not None]
    expected = sum(f.weight * f.normalized for f in included) / sum(f.weight for f in included) * 100
    assert lone.score == pytest.approx(expected, abs=0.1)


def test_scoring_never_invents_demand_or_performance():
    """A page that literally prints performance/availability numbers: the
    facts are recorded as provenance (observed OF THE PAGE), but no factor,
    signal, or disclosure may turn them into a demand/performance/availability
    measure."""
    poisoned = _record(
        "poison", "https://market.example.test/poison",
        "5kW hybrid inverter - hyped listing", "market",
        [("product", "5kW hybrid inverter"), ("asking_price", "1500"), ("currency", "USD"),
         ("ctr", "12.4"), ("impressions", "45000"), ("stock_status", "selling fast")],
    )
    verdict = score_records([poisoned, _supplier_a(), _supplier_b()],
                            product="5kW hybrid inverter",
                            required_keys=["unit_price"], now=NOW)
    banned = {"ctr", "impressions", "stock_status", "demand", "availability"}
    for factor in verdict.factors:
        assert factor.name not in banned
        assert not any(word in factor.signal.lower() for word in banned)
    assert any("excluded from every signal" in d for d in verdict.disclosures)
    assert any("demand" in d for d in verdict.disclosures)


def test_mixed_currency_spread_excluded():
    verdict = score_records(
        [_supplier_a(), _market_usd(), _market_ghs()],
        product="5kW hybrid inverter", required_keys=["unit_price"], now=NOW,
    )
    spread = next(f for f in verdict.factors if f.name == "price_spread")
    assert not spread.included and "mixed currencies" in spread.reason
    assert "price_spread" in verdict.excluded


# -- deliverable #4: supplier and listing comparison -------------------------------------


def test_supplier_comparison_roles_conflicts_and_citations():
    from commerce_adapter import compare_suppliers

    records = [_supplier_a(), _supplier_b(), _tariff()]
    types = {r.source_id: r.note.removeprefix("source_type=") for r in records}
    verdict = compare_suppliers(records, types, required_keys=["duty_rate_pct", "moq"])
    assert len(verdict.suppliers) == 2 and len(verdict.official) == 1
    subjects = {row.subject for row in verdict.rows}
    assert {"unit_price", "moq", "lead_time_days", "duty_rate_pct"} <= subjects
    conflict_subjects = {c["subject"] for c in verdict.conflicts}
    assert {"unit_price", "moq", "warranty_months"} <= conflict_subjects
    for row in verdict.rows:
        for value in row.values:
            assert value["citation"].startswith("[S"), "every value keeps its citation"
    # duty rate came from the official schedule -> observed, explicitly based
    duty_values = next(r for r in verdict.rows if r.subject == "duty_rate_pct").values
    assert all(v["kind"] == "observed" for v in duty_values)
    assert verdict.gaps == [], "both required keys covered"
    # without an official source the comparison discloses that rates are assumptions
    no_official = compare_suppliers([_supplier_a(), _supplier_b()], types)
    assert any("no official published rate" in d for d in no_official.disclosures)


# -- deliverable #5: vehicle auction research --------------------------------------------


def test_vehicle_check_matches_mismatches_and_unknown_keys():
    from commerce_adapter import check_vehicles

    auction = _record(
        "lot42", "https://auctions.example.test/lot/hilux-2019-lot42",
        "Auction lot 42 - 2019 Toyota Hilux", "auction",
        [("make", "Toyota"), ("model", "Hilux"), ("year", "2019"), ("mileage_km", "118000"),
         ("reserve_price", "21000"), ("currency", "USD")],
    )
    dealer = _record(
        "deal", "https://dealer.example.test/trucks/hilux-2019",
        "2019 Toyota Hilux - dealer listing", "dealer",
        [("make", "Toyota"), ("model", "Hilux"), ("year", "2019"), ("mileage_km", "132500"),
         ("asking_price", "22800"), ("currency", "USD")],
    )
    verdict = check_vehicles(
        [auction, dealer],
        {"make": "Toyota", "model": "Hilux", "year_min": "2015", "year_max": "2021",
         "mileage_km_max": "120000", "budget_max": "25000", "color": "red"},
    )
    assert len(verdict.rows) == 2
    by_id = {r.source_id: r for r in verdict.rows}
    assert "mileage_km_max" in [m["key"] for m in by_id["deal"].mismatches]
    assert by_id["lot42"].mismatches == []
    assert all(r.citation.startswith("[S") for r in verdict.rows)
    # prices keep their snapshot typing
    for r in verdict.rows:
        for price in r.prices:
            assert price["kind"] == "estimate" and "snapshot" in price["note"]
    assert any("unknown spec key" in d and "color" in d for d in verdict.disclosures)
    # cross-source mileage conflict surfaced, never averaged
    subjects = {c["subject"] for c in verdict.conflicts}
    assert "mileage_km" in subjects


def test_vehicle_check_without_vehicle_sources_discloses():
    from commerce_adapter import check_vehicles

    verdict = check_vehicles([_supplier_a()], {"make": "Toyota"})
    assert verdict.rows == []
    assert any("no fetched source carried vehicle attributes" in d for d in verdict.disclosures)


# -- deliverable #6: landed-cost estimate template ----------------------------------------


def test_landed_cost_template_types_lines():
    result = compute_landed_cost(
        unit_price=22800, currency="usd", qty=2, shipping_total=800,
        duty_rate_pct=5, unit_price_kind="estimate", duty_kind="observed",
    )
    kinds = {line.key: line.kind for line in result.lines}
    bases = {line.key: line.basis for line in result.lines}
    assert kinds["unit_price"] == "estimate" and "asking price" in bases["unit_price"]
    assert kinds["duty"] == "observed" and "official" in bases["duty"]
    assert kinds["shipping"] == "assumption"
    # arithmetic: (22800 + 1140 + 400) * 2
    assert result.landed_unit == pytest.approx(22800 + 22800 * 0.05 + 400)
    assert result.landed_total == pytest.approx((22800 + 22800 * 0.05 + 400) * 2)
    joined = " ".join(result.disclosures)
    assert "ESTIMATE" in joined and "not a quotation" in joined
    assert "no verified transaction cost" in joined
    # unbound duty is disclosed as an assumption, not dressed as official
    unbound = compute_landed_cost(unit_price=100, currency="USD", duty_rate_pct=5)
    assert any("typed as an assumption" in d for d in unbound.disclosures)


def test_landed_cost_refuses_invalid_inputs():
    with pytest.raises(LandedCostError):
        compute_landed_cost(unit_price=100, currency="")
    with pytest.raises(LandedCostError):
        compute_landed_cost(unit_price=100, currency="USD", qty=0)
    with pytest.raises(LandedCostError):
        compute_landed_cost(unit_price=100, currency="USD", duty_rate_pct=150)
    with pytest.raises(LandedCostError):
        compute_landed_cost(unit_price=-5, currency="USD")


# -- deliverable #2 / acceptance #1 + #3: ad-library integration --------------------------


async def test_ad_library_provider_honesty():
    provider = CannedAdLibraryProvider(_corpus())
    hit = await provider.search("solar inverter ad")
    assert hit.mode == "canned"
    assert CANNED_DISCLOSURE in hit.disclosures
    assert len(hit.ads) == 1 and "ads.example.test" in hit.ads[0]["url"]
    # zero matches stay zero: no fixture, no result, no filler
    miss = await provider.search("hair dryer salon promotion")
    assert miss.ads == [] and any("zero results" in d for d in miss.disclosures)


def test_ad_library_summarize_excludes_performance():
    from commerce_adapter import commerce_facts

    facts = commerce_facts(
        [("advertiser", "SunGrid Ltd"), ("ad_id", "AD-88123"), ("regions", "NG, GH"),
         ("creative", "5kW hybrid inverter"), ("ctr", "12.4")],
        source_type="ad_library", retrieved_at=NOW,
    )
    attributes, disclosures = summarize_ad(facts)
    assert attributes == {"advertiser": "SunGrid Ltd", "ad_id": "AD-88123",
                          "regions": "NG, GH", "creative": "5kW hybrid inverter"}
    assert "ctr" not in attributes
    assert any("performance" in d and "ctr" in d for d in disclosures)
    # the raw fact is still in provenance — recorded, never summarized
    assert any(f.key == "ctr" for f in facts)


# -- registry over the application DB ------------------------------------------------------


def _product_task(task_id: str, user_id: str) -> Task:
    return Task(id=task_id, user_id=user_id, objective="5kW inverter sourcing",
                status="running", budget_xp=60)


async def _fetched_registry(session, dev_user, settings, *, urls: list[str]):
    """Registry with the named commerce pages fetched (source rows persisted)."""
    task = _product_task("task-commerce-1", dev_user.id)
    session.add(task)
    await session.commit()
    registry = build_product_registry(
        session=session, task=task, settings=settings, storage=LocalStorage(settings.artifact_dir)
    )
    source_ids: dict[str, str] = {}
    for url in urls:
        out = await registry.execute("web.fetch_page", {"url": url}, {"research:read"})
        assert out["status"] == "ok", out
        source_ids[url] = out["source_id"]
    return registry, task, source_ids


async def test_commerce_registry_end_to_end(session, dev_user, settings):
    task = _product_task("task-commerce-2", dev_user.id)
    session.add(task)
    await session.commit()
    registry = build_product_registry(
        session=session, task=task, settings=settings, storage=LocalStorage(settings.artifact_dir)
    )

    # the merged corpus is reachable through the SAME search wall
    search = await registry.execute(
        "web.search", {"query": "5kw hybrid inverter supplier quote", "limit": 6},
        {"research:read"},
    )
    assert search["status"] == "ok" and search["results"]
    assert any("supplier.example.test" in r["url"] for r in search["results"])

    # commerce fetch typing: supplier unit price is an ESTIMATE (quotation
    # snapshot), official duty rate is OBSERVED (published rate)
    sup = await registry.execute(
        "web.fetch_page", {"url": "https://supplier.example.test/energy/inverter-5kw-quote"},
        {"research:read"},
    )
    assert sup["status"] == "ok"

    sup_row = (await session.execute(
        select(ResearchSource).where(
            ResearchSource.task_id == task.id,
            ResearchSource.url == "https://supplier.example.test/energy/inverter-5kw-quote",
        )
    )).scalars().one()
    facts = {f["key"]: f for f in sup_row.facts}
    assert facts["unit_price"]["kind"] == "estimate"
    assert "supplier quotation snapshot" in facts["unit_price"]["note"]

    tariff_row = None
    await registry.execute(
        "web.fetch_page", {"url": "https://tariff.example.test/ng/import-duty-solar"},
        {"research:read"},
    )
    tariff_row = (await session.execute(
        select(ResearchSource).where(
            ResearchSource.task_id == task.id,
            ResearchSource.url == "https://tariff.example.test/ng/import-duty-solar",
        )
    )).scalars().one()
    tariff_facts = {f["key"]: f for f in tariff_row.facts}
    assert tariff_facts["duty_rate_pct"]["kind"] == "observed"
    assert "official published rate" in tariff_facts["duty_rate_pct"]["note"]

    # supplier comparison over the collected rows
    await registry.execute(
        "web.fetch_page", {"url": "https://supplier.example.test/energy/inverter-5kw-quote-b"},
        {"research:read"},
    )
    compared = await registry.execute(
        "commerce.compare_suppliers", {"required_keys": ["moq"]}, {"research:read"}
    )
    assert compared["status"] == "ok"
    assert len(compared["suppliers"]) == 2
    assert any(c["subject"] == "unit_price" for c in compared["conflicts"])

    # scoring with the configured factor table
    scored = await registry.execute(
        "commerce.score",
        {"product": "5kW hybrid inverter", "required_keys": ["unit_price", "moq"]},
        {"research:read"},
    )
    assert scored["status"] == "ok"
    assert scored["config_echo"]
    assert any("demand" in d for d in scored["disclosures"])
    event = (await session.execute(
        select(TaskEvent).where(
            TaskEvent.task_id == task.id, TaskEvent.event_type == "commerce.scored"
        )
    )).scalars().first()
    assert event is not None and event.payload["product"] == "5kW hybrid inverter"

    # vehicle check over auction + dealer fixtures
    await registry.execute(
        "web.fetch_page", {"url": "https://auctions.example.test/lot/hilux-2019-lot42"},
        {"research:read"},
    )
    await registry.execute(
        "web.fetch_page", {"url": "https://dealer.example.test/trucks/hilux-2019"},
        {"research:read"},
    )
    checked = await registry.execute(
        "commerce.vehicle_check",
        {"specs": {"make": "Toyota", "model": "Hilux", "mileage_km_max": "120000"}},
        {"research:read"},
    )
    assert checked["status"] == "ok" and len(checked["rows"]) == 2
    dealer_row = next(r for r in checked["rows"] if "dealer" in r["title"])
    assert any(m["key"] == "mileage_km_max" for m in dealer_row["mismatches"])

    # ad-library: search + fetch with performance exclusion
    ads = await registry.execute(
        "commerce.ad_library_search", {"query": "solar inverter ad"}, {"research:read"}
    )
    assert ads["status"] == "ok" and len(ads["results"]) == 1
    assert any("no live or private ad library" in d for d in ads["disclosures"])
    ad_url = ads["results"][0]["url"]
    ad = await registry.execute("commerce.fetch_ad", {"url": ad_url}, {"research:read"})
    assert ad["status"] == "ok"
    assert "advertiser" in ad["ad_attributes"] and "ctr" not in ad["ad_attributes"]
    assert any("performance" in d for d in ad["disclosures"])


async def test_landed_cost_bound_source_value_wins(session, dev_user, settings):
    """The model cites [S2] for the unit price: the LINE VALUE must come from
    that source's persisted fact, not from the model's own number."""
    registry, _task, source_ids = await _fetched_registry(
        session, dev_user, settings,
        urls=[
            "https://supplier.example.test/energy/inverter-5kw-quote",
            "https://tariff.example.test/ng/import-duty-solar",
        ],
    )
    sup_id = source_ids["https://supplier.example.test/energy/inverter-5kw-quote"]
    tariff_id = source_ids["https://tariff.example.test/ng/import-duty-solar"]

    out = await registry.execute(
        "commerce.landed_cost",
        {
            "unit_price": 999.0,  # the model tries to pass its own number
            "currency": "USD",
            "qty": 10,
            "shipping_total": 380,
            "unit_price_source_id": sup_id,
            "duty_source_id": tariff_id,
        },
        {"research:read"},
    )
    assert out["status"] == "ok"
    lines = {line["key"]: line for line in out["lines"]}
    assert lines["unit_price"]["value"] == 1450.0, "bound source fact wins"
    assert lines["unit_price"]["kind"] == "estimate"
    assert lines["unit_price"]["citation"], "the bound line keeps its citation"
    assert lines["duty"]["value"] == pytest.approx(1450 * 0.05)
    assert lines["duty"]["kind"] == "observed"
    assert out["landed_total"] == pytest.approx((1450 + 72.5 + 38.0) * 10)


async def test_landed_cost_binding_refuses_foreign_sources(session, dev_user, settings):
    registry, task, _source_ids = await _fetched_registry(
        session, dev_user, settings,
        urls=["https://supplier.example.test/energy/inverter-5kw-quote"],
    )
    # a made-up source id cannot be cited
    with pytest.raises(LandedCostError):
        await registry.execute(
            "commerce.landed_cost",
            {"unit_price": 100, "currency": "USD", "unit_price_source_id": "nope"},
            {"research:read"},
        )
    # a source without a price fact cannot back the unit price
    await registry.execute(
        "web.fetch_page", {"url": "https://tariff.example.test/ng/import-duty-solar"},
        {"research:read"},
    )
    tariff_row = (await session.execute(
        select(ResearchSource).where(
            ResearchSource.task_id == task.id,
            ResearchSource.url == "https://tariff.example.test/ng/import-duty-solar",
        )
    )).scalars().one()
    with pytest.raises(LandedCostError):
        await registry.execute(
            "commerce.landed_cost",
            {"unit_price": 100, "currency": "USD", "unit_price_source_id": tariff_row.id},
            {"research:read"},
        )


async def test_commerce_tools_scope_wall_and_costs(session, dev_user, settings):
    task = _product_task("task-commerce-3", dev_user.id)
    session.add(task)
    await session.commit()
    registry = build_product_registry(
        session=session, task=task, settings=settings, storage=LocalStorage(settings.artifact_dir)
    )
    specs = {s.name: s for s in registry.list_specs()}
    commerce_tools = [n for n in specs if n.startswith("commerce.")]
    assert set(commerce_tools) == {
        "commerce.compare_suppliers", "commerce.score", "commerce.vehicle_check",
        "commerce.landed_cost", "commerce.ad_library_search", "commerce.fetch_ad",
    }
    for name in commerce_tools:
        assert specs[name].category == "commerce_intelligence"
        assert specs[name].required_scope == "research:read"
        assert not specs[name].requires_approval, "read-only commerce tools never gate"
    for name in commerce_tools:
        with pytest.raises(ScopeDenied):
            await registry.execute(name, {}, set())
    # no wallet/signing surface anywhere in the merged registry
    for name in specs:
        assert not any(w in name.lower() for w in ("wallet", "sign", "seed", "phrase"))


async def test_scoring_config_fallback_disclosed(session, dev_user, settings, monkeypatch):
    """A broken operator config degrades to documented defaults WITH a
    disclosure in the tool output — never silently, never a crash."""
    monkeypatch.setattr(settings, "commerce_scoring_factors", "{broken json")
    registry, _task, _ids = await _fetched_registry(
        session, dev_user, settings,
        urls=["https://supplier.example.test/energy/inverter-5kw-quote"],
    )
    out = await registry.execute(
        "commerce.score", {"product": "5kW hybrid inverter"}, {"research:read"}
    )
    assert out["status"] == "ok"
    assert out["config_echo"] == DEFAULT_FACTORS
    assert any("invalid JSON" in d for d in out["disclosures"])


# -- explicit task result: freshness/confidence + scored verdict --------------------------

class _Scripted:
    def __init__(self, plan: dict) -> None:
        self.plan = plan

    async def complete(self, messages, tools=None):
        return {
            "content": json.dumps(self.plan),
            "tool_calls": [],
            "finish_reason": "stop",
            "model": "scripted",
            "revision_id": "test",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                      "cache_hit_tokens": 0, "estimated_cost_usd": 0.0},
        }


async def test_result_endpoint_carries_freshness_confidence_and_scored(
    client, session, dev_user, monkeypatch
):
    from xp_core.services import ledger

    await ledger.credit_purchase(session, user_id=dev_user.id, amount=200,
                                 payment_intent_id="seed-200")
    await session.commit()

    goal = "5kW inverter sourcing and landed cost"
    monkeypatch.setattr(
        agent_service,
        "make_chat_client",
        lambda s: _Scripted(
            {
                "plan": [
                    {"step": 1, "tool": "web.fetch_page", "why": "quote",
                     "arguments": {"url": "https://supplier.example.test/energy/inverter-5kw-quote"}},
                    {"step": 2, "tool": "web.fetch_page", "why": "rate",
                     "arguments": {"url": "https://tariff.example.test/ng/import-duty-solar"}},
                    {"step": 3, "tool": "commerce.score", "why": "score",
                     "arguments": {"product": "5kW hybrid inverter",
                                   "required_keys": ["unit_price", "moq"]}},
                    {"step": 4, "tool": "docs.generate_pdf", "why": "deliver",
                     "arguments": {"title": "Inverter sourcing report"}},
                ],
                "estimated_xp": 19,
                "deliverable": f"Report: {goal}",
            }
        ),
    )
    task = (await client.post(
        "/api/v1/tasks", json={"objective": goal, "budget_xp": 60}
    )).json()
    resp = await client.post(f"/api/v1/tasks/{task['id']}/run")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "completed"
    # fetch 2 + fetch 2 + score 5 + pdf 10 = 19
    assert body["actual_xp"] == 19

    result = (await client.get(f"/api/v1/tasks/{task['id']}/result")).json()
    for source in result["sources"]:
        assert source["freshness"] in {"fresh", "recent", "stale", "outdated", "unknown"}
        assert source["confidence"] in {"high", "medium", "low"}
    scored = result["scored"]
    assert scored is not None and scored["product"] == "5kW hybrid inverter"
    assert {f["name"] for f in scored["factors"]} == set(DEFAULT_FACTORS)
    assert scored["config_echo"] == DEFAULT_FACTORS
    assert any("demand" in d for d in scored["disclosures"])
    # the PDF renders the scored context too (quality gates still enforced)
    assert result["artifacts"], "PDF attached"


# -- report integration -------------------------------------------------------------------


def test_report_renders_commerce_fact_kinds():
    """Asking prices stay estimates and official rates stay observed in the
    rendered report HTML (acceptance #2 at the presentation layer)."""
    from xp_core.services.documents import (
        ReportClaim,
        ReportSource,
        ReportSpec,
    )

    spec = ReportSpec(
        title="Sourcing report",
        goal="5kW inverter",
        generated_at=NOW,
        claims=[
            ReportClaim(text="unit price: 1450 (supplier quotation snapshot)", citations=[1],
                        kind="estimate"),
            ReportClaim(text="duty rate pct: 5 (official published rate)", citations=[2],
                        kind="observed"),
        ],
        sources=[
            ReportSource(index=1, url="https://supplier.example.test/x", title="Supplier A",
                         status="ok", retrieval_mode="canned"),
            ReportSource(index=2, url="https://tariff.example.test/x", title="Tariff",
                         status="ok", retrieval_mode="canned"),
        ],
        limitations=["no verified transaction cost exists in this pipeline"],
        task_id="t",
        mode_notes=["canned mode"],
    )
    html = render_report_html(spec)
    assert "kind-estimate" in html and "kind-observed" in html
    assert "official published rate" in html
