"""Repeatable commerce evaluation set (phase-8 acceptance criteria).

The committed JSON set (default ``tests/data/commerce_eval_set.json``) holds
a fixed corpus of offline commerce fixtures (suppliers, market listings, an
official tariff, an ad-library page, auction/dealer vehicle sources) and
evaluation cases. The runner executes each case's workflow — search
(web and/or ad library), permitted fetches with commerce fact typing, then
the commerce operation (score / compare suppliers / vehicle check / landed
cost) — and checks the phase-8 quality bars deterministically:

- only accessible, permitted fixtures are represented as searched
- asking prices are estimates, official rates are observed, user inputs are
  assumptions — and the distinction survives into every output
- no demand, ad-performance, or availability measure is ever invented
  (scoring exposes no such factor; ad summaries exclude performance keys)
- scoring factors and their weights are visible and echoed

Same inputs -> same verdicts. Run via ``make commerce-eval``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_adapter.provenance import SourceRecord, unavailable_record
from research_adapter.providers import CannedSearchProvider

from commerce_adapter.adlibrary import CannedAdLibraryProvider, summarize_ad
from commerce_adapter.classify import commerce_facts
from commerce_adapter.landed import compute_landed_cost
from commerce_adapter.providers import CommerceFetchProvider
from commerce_adapter.scoring import score_records
from commerce_adapter.suppliers import compare_suppliers
from commerce_adapter.vehicles import check_vehicles

EVAL_RETRIEVED_AT = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def load_commerce_eval_set(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"commerce evaluation set not found: {p}")
    return json.loads(p.read_text())


async def _records_for_case(
    case: dict[str, Any], corpus: list[dict[str, Any]]
) -> tuple[
    list[SourceRecord],
    dict[str, str],
    list[dict[str, str]],
    list[dict[str, Any]],
]:
    """Run the case's search(es) + fetches.

    Returns (records, source_types by source_id, ad_library listings,
    ad_summaries for fetched ad pages).
    """
    search = CannedSearchProvider(corpus)
    fetch = CommerceFetchProvider(corpus)
    ads_provider = CannedAdLibraryProvider(corpus)

    records: list[SourceRecord] = []
    source_types: dict[str, str] = {}
    ads_out: list[dict[str, str]] = []
    ad_summaries: list[dict[str, Any]] = []
    counter = 0

    steps = case.get("steps", {})

    if steps.get("search_query"):
        outcome = await search.search(str(steps["search_query"]), limit=int(steps.get("limit", 5)))
        for listing in outcome.results:
            counter += 1
            records.append(
                SourceRecord(
                    source_id=f"listed-{counter}",
                    url=listing.url,
                    title=listing.title,
                    status="listed",
                    retrieval_mode="canned",
                    note="found by web.search; not fetched",
                )
            )

    if steps.get("ad_library_query"):
        outcome = await ads_provider.search(
            str(steps["ad_library_query"]), limit=int(steps.get("ad_limit", 5))
        )
        for ad in outcome.ads:
            counter += 1
            records.append(
                SourceRecord(
                    source_id=f"adlisted-{counter}",
                    url=ad["url"],
                    title=ad["title"],
                    status="listed",
                    retrieval_mode="canned",
                    note="found by commerce.ad_library_search; not fetched",
                )
            )
            ads_out.append({"url": ad["url"], "title": ad["title"]})

    for url in steps.get("fetch_urls", []):
        counter += 1
        sid = f"fetched-{counter}"
        outcome = await fetch.fetch(url)
        if outcome.status == "ok" and outcome.page is not None:
            facts = commerce_facts(
                [(f.key, f.value) for f in outcome.page.facts],
                source_type=outcome.source_type,
                retrieved_at=EVAL_RETRIEVED_AT,
            )
            records.append(
                SourceRecord(
                    source_id=sid,
                    url=outcome.url,
                    title=outcome.page.title,
                    status="ok",
                    retrieved_at=EVAL_RETRIEVED_AT,
                    facts=facts,
                    content_sha256=outcome.page.content_sha256,
                    retrieval_mode="canned",
                    note=f"source_type={outcome.source_type}",
                )
            )
            source_types[sid] = outcome.source_type
        else:
            records.append(unavailable_record(sid, url, outcome.status, outcome.reason))

    # fetched ad-library pages are summarized here so the eval can assert
    # the no-performance contract at adapter level
    for record in records:
        if source_types.get(record.source_id) == "ad_library":
            attributes, disclosures = summarize_ad(record.facts)
            record.note = f"source_type=ad_library; summarized={sorted(attributes)}"
            for d in disclosures:
                record.note += f"; {d}"
            ad_summaries.append(
                {"url": record.url, "attributes": attributes, "disclosures": disclosures}
            )

    return records, source_types, ads_out, ad_summaries


def _run_operation(
    case: dict[str, Any],
    records: list[SourceRecord],
    source_types: dict[str, str],
    now: datetime,
) -> tuple[str, dict[str, Any]]:
    steps = case.get("steps", {})
    op = steps.get("operation", {})
    tool = str(op.get("tool", ""))
    args = dict(op.get("args", {}))
    if tool == "commerce.score":
        verdict = score_records(
            records,
            product=args.get("product"),
            required_keys=args.get("required_keys") or [],
            now=now,
        )
        return tool, verdict.as_dict()
    if tool == "commerce.compare_suppliers":
        verdict = compare_suppliers(
            records, source_types, required_keys=args.get("required_keys") or []
        )
        return tool, verdict.as_dict()
    if tool == "commerce.vehicle_check":
        verdict = check_vehicles(records, {str(k): str(v) for k, v in args.get("specs", {}).items()})
        return tool, verdict.as_dict()
    if tool == "commerce.landed_cost":
        result = compute_landed_cost(
            unit_price=args["unit_price"],
            currency=args["currency"],
            qty=int(args.get("qty", 1)),
            shipping_total=float(args.get("shipping_total", 0.0)),
            insurance=float(args.get("insurance", 0.0)),
            duty_rate_pct=float(args.get("duty_rate_pct", 0.0)),
            flat_fees=float(args.get("flat_fees", 0.0)),
            unit_price_kind=args.get("unit_price_kind", "estimate"),
            duty_kind=args.get("duty_kind", "assumption"),
        )
        return tool, result.as_dict()
    raise ValueError(f"unknown eval operation {tool!r}")


def _check(expect_kind: str, output: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if expect_kind == "commerce.score":
        factors = {f["name"]: f for f in output["factors"]}
        if expect.get("config_echo") is not None and output.get("config_echo") != expect.get(
            "config_echo"
        ):
            failures.append(
                f"config echo {output.get('config_echo')} != expected {expect.get('config_echo')}"
            )
        for name in expect.get("factors_visible", []):
            if name not in factors:
                failures.append(f"factor {name} missing from the verdict")
        for name in expect.get("factors_excluded", []):
            if name in factors and factors[name]["included"]:
                failures.append(f"factor {name} should be excluded but was included")
        banned = {"demand", "ad_performance", "ctr", "availability", "stock"}
        leaked = sorted(set(output.get("config_echo", {})) & banned)
        if leaked:
            failures.append(f"scoring config contains forbidden factors: {leaked}")
        if not any("demand" in d for d in output["disclosures"]):
            failures.append("the no-demand disclosure is missing")
    if expect_kind == "commerce.compare_suppliers":
        subjects = {r["subject"] for r in output["rows"]}
        for subject in expect.get("conflict_subjects", []):
            if subject not in subjects:
                failures.append(f"expected compared subject {subject} missing")
        conflict_subjects = {c["subject"] for c in output["conflicts"]}
        for subject in expect.get("conflicts", []):
            if subject not in conflict_subjects:
                failures.append(f"expected conflict on {subject} not surfaced")
        if expect.get("supplier_count") is not None and len(output["suppliers"]) != int(
            expect["supplier_count"]
        ):
            failures.append(
                f"supplier count {len(output['suppliers'])} != {expect['supplier_count']}"
            )
    if expect_kind == "commerce.vehicle_check":
        if expect.get("rows") is not None and len(output["rows"]) != int(expect["rows"]):
            failures.append(f"vehicle rows {len(output['rows'])} != {expect['rows']}")
        mismatch_keys = sorted(
            {m["key"] for r in output["rows"] for m in r["mismatches"]}
        )
        for key in expect.get("mismatch_keys", []):
            if key not in mismatch_keys:
                failures.append(f"expected mismatch on {key} not flagged")
        conflict_subjects = {c["subject"] for c in output["conflicts"]}
        for subject in expect.get("conflicts", []):
            if subject not in conflict_subjects:
                failures.append(f"expected vehicle conflict on {subject} not surfaced")
    if expect_kind == "commerce.landed_cost":
        kinds = {line["key"]: line["kind"] for line in output["lines"]}
        for key, kind in (expect.get("line_kinds") or {}).items():
            if kinds.get(key) != kind:
                failures.append(f"line {key} kind {kinds.get(key)!r} != expected {kind!r}")
        if expect.get("landed_total") is not None and abs(
            output["landed_total"] - float(expect["landed_total"])
        ) > 0.01:
            failures.append(
                f"landed_total {output['landed_total']} != {expect['landed_total']}"
            )
        if not any("not a quotation" in d for d in output["disclosures"]):
            failures.append("the not-a-quotation disclosure is missing")
    return failures


async def run_commerce_eval_case(case: dict[str, Any], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    name = str(case.get("name", "unnamed"))
    expect = case.get("expect", {})
    checks: dict[str, Any] = {}
    failures: list[str] = []

    records, source_types, ads_out, ad_summaries = await _records_for_case(case, corpus)
    fetched_ok = [r for r in records if r.status == "ok"]
    checks["sources_fetched_ok"] = len(fetched_ok)
    if len(fetched_ok) < int(expect.get("min_sources", 0)):
        failures.append(
            f"expected >= {expect.get('min_sources')} fetched sources, got {len(fetched_ok)}"
        )

    # -- ad-library assertions --------------------------------------------------
    if expect.get("ads") is not None and len(ads_out) != int(expect["ads"]):
        failures.append(f"ad-library results {len(ads_out)} != expected {expect['ads']}")
    if expect.get("ad_attributes_contains"):
        for summary in ad_summaries:
            for key in expect["ad_attributes_contains"]:
                if key not in summary["attributes"]:
                    failures.append(f"ad summary is missing attribute {key}")
    if expect.get("ad_attributes_excludes"):
        for summary in ad_summaries:
            for key in expect["ad_attributes_excludes"]:
                if key in summary["attributes"]:
                    failures.append(
                        f"ad summary must exclude performance metric {key}"
                    )
    if expect.get("ad_performance_excluded"):
        for summary in ad_summaries:
            if not summary["disclosures"] or not any(
                "performance" in d for d in summary["disclosures"]
            ):
                failures.append(
                    "an ad page carried performance metrics but the exclusion "
                    "disclosure is missing"
                )

    # -- operation ------------------------------------------------------------
    steps = case.get("steps", {})
    if steps.get("operation"):
        tool, output = _run_operation(case, records, source_types, EVAL_RETRIEVED_AT)
        checks["operation"] = tool
        checks["output"] = output
        failures.extend(_check(tool, output, expect))

    return {
        "name": name,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
    }


def run_commerce_eval_set(path: str | Path) -> dict[str, Any]:
    data = load_commerce_eval_set(path)
    corpus = data["corpus"]
    verdicts = [
        asyncio.run(run_commerce_eval_case(case, corpus)) for case in data["cases"]
    ]
    passed = sum(1 for v in verdicts if v["passed"])
    return {
        "cases": verdicts,
        "passed": passed,
        "total": len(verdicts),
        "ok": passed == len(verdicts),
    }


__all__ = [
    "load_commerce_eval_set",
    "run_commerce_eval_case",
    "run_commerce_eval_set",
]
