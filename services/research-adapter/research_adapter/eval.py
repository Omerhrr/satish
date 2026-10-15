"""Repeatable research evaluation set (phase-7 acceptance #5).

The committed JSON set (default ``tests/data/research_eval_set.json``) holds
a fixed corpus of offline pages and a list of evaluation cases. The runner
executes the full research workflow over each case — search, permitted
fetch, fact classification, cross-source comparison, report build — and
checks the phase-7 quality bars deterministically:

- every claim in the generated report is cited
- conflicts between sources are detected and disclosed
- unavailable sources and coverage gaps are disclosed
- listing-snapshot prices are typed 'estimate', never presented as live
- the rendered PDF passes structural validation

Same inputs -> same verdicts; the committed set is the regression harness
for the research pipeline. Run it via ``make research-eval`` or the pytest
tests in tests/test_research_eval.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xp_core.services.documents import (
    ReportClaim,
    ReportSource,
    ReportSpec,
    check_report_spec,
    render_report_pdf,
    validate_document,
)

from research_adapter.compare import compare_sources
from research_adapter.provenance import (
    SourceRecord,
    facts_from_extraction,
    unavailable_record,
)
from research_adapter.providers import CannedFetchProvider, CannedSearchProvider

EVAL_RETRIEVED_AT = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def load_eval_set(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"research evaluation set not found: {p}")
    return json.loads(p.read_text())


async def _records_for_case(
    case: dict[str, Any], corpus: list[dict[str, Any]]
) -> tuple[list[SourceRecord], list[dict[str, str]]]:
    """Run search + fetch for one case; return (records, search_listings)."""
    search = CannedSearchProvider(corpus)
    fetch = CannedFetchProvider(corpus)

    listed: list[dict[str, str]] = []
    records: list[SourceRecord] = []

    search_outcome = await search.search(str(case.get("goal", "")), limit=int(case.get("limit", 5)))
    counter = 0

    for listing in search_outcome.results:
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
        listed.append({"url": listing.url, "title": listing.title})

    for url in case.get("fetch_urls", []):
        counter += 1
        sid = f"fetched-{counter}"
        outcome = await fetch.fetch(url)
        if outcome.status == "ok" and outcome.page is not None:
            facts = facts_from_extraction(
                [(f.key, f.value) for f in outcome.page.facts],
                is_listing_snapshot=outcome.is_listing_snapshot,
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
                )
            )
        else:
            records.append(
                unavailable_record(sid, url, outcome.status, outcome.reason)
            )
    return records, listed


def _build_spec(name: str, records: list[SourceRecord], goal: str) -> ReportSpec:
    """Adapter-level report builder — mirrors the API builder's contract:
    claims only from fetched-ok facts, every claim cited, unreachable and
    listed-only sources disclosed."""
    sources: list[ReportSource] = []
    index_of: dict[str, int] = {}
    claims: list[ReportClaim] = []
    for i, record in enumerate(records, start=1):
        index_of[record.source_id] = i
        sources.append(
            ReportSource(
                index=i,
                url=record.url,
                title=record.title,
                status=record.status,
                retrieved_at=record.retrieved_at,
                fact_count=len(record.facts),
                retrieval_mode=record.retrieval_mode,
            )
        )
        if record.status != "ok":
            continue
        for fact in record.facts:
            text = f"{fact.key.replace('_', ' ')}: {fact.value}"
            if fact.note:
                text += f" ({fact.note})"
            claims.append(ReportClaim(text=text, citations=[index_of[record.source_id]], kind=fact.kind))

    comparison = compare_sources(records)
    unavailable = [
        f"S{index_of[r.source_id]} {r.url} — {r.status}: {r.note or 'no reason recorded'}"
        for r in records
        if r.status in {"unavailable", "denied", "error"}
    ]
    estimate_keys = sorted(
        {row.subject for row in comparison.rows if any(v["kind"] == "estimate" for v in row.values)}
    )
    limitations = [
        "claims reflect what the fetched pages said at retrieval time",
        "structural quality gates only — sources remain the user's responsibility to review",
    ]
    if estimate_keys:
        limitations.append(
            f"figures for {', '.join(estimate_keys)} are listing snapshots (estimates), "
            "not live quotes"
        )
    if not records:
        limitations.append("no sources were collected — disclosures only, no findings")
    return ReportSpec(
        title=f"Evaluation report: {name}",
        goal=goal,
        generated_at=EVAL_RETRIEVED_AT,
        claims=claims,
        conflicts=[
            {"subject": c.subject, "detail": c.detail, "values": c.values}
            for c in comparison.conflicts
        ],
        gaps=list(comparison.gaps),
        sources=sources,
        unavailable=unavailable,
        limitations=limitations,
        task_id="eval-set",
        mode_notes=[
            "search mode: canned (committed offline evaluation corpus)",
            "fetch mode: canned",
            *comparison.disclosures,
        ],
    )


async def run_eval_case(case: dict[str, Any], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    name = str(case.get("name", "unnamed"))
    expect = case.get("expect", {})
    checks: dict[str, Any] = {}
    failures: list[str] = []

    records, listings = await _records_for_case(case, corpus)
    fetched_ok = [r for r in records if r.status == "ok"]
    checks["sources_fetched_ok"] = len(fetched_ok)
    if len(fetched_ok) < int(expect.get("min_sources", 0)):
        failures.append(
            f"expected >= {expect.get('min_sources')} fetched sources, got {len(fetched_ok)}"
        )

    comparison = compare_sources(records, case.get("required_keys") or [])
    conflict_subjects = sorted(c.subject for c in comparison.conflicts)
    checks["conflict_subjects"] = conflict_subjects
    expected_conflicts = sorted(expect.get("conflicts", []))
    if conflict_subjects != expected_conflicts:
        failures.append(f"conflicts {conflict_subjects} != expected {expected_conflicts}")

    checks["gaps"] = sorted(comparison.gaps)
    expected_gaps = sorted(expect.get("gaps", []))
    if checks["gaps"] != expected_gaps:
        failures.append(f"gaps {checks['gaps']} != expected {expected_gaps}")

    spec = _build_spec(name, records, str(case.get("goal", "")))
    violations = check_report_spec(spec)
    checks["quality_violations"] = violations
    if violations:
        failures.append(f"report spec violated quality gates: {violations}")

    citations_ok = all(c.citations for c in spec.claims)
    checks["claims_all_cited"] = citations_ok
    if not citations_ok:
        failures.append("some claims lack citations")

    estimate_subjects = sorted(
        {
            f"{claim.text.split(':')[0].strip().replace(' ', '_')}"
            for claim in spec.claims
            if claim.kind == "estimate"
        }
    )
    checks["estimate_subjects"] = estimate_subjects
    expected_estimates = sorted(expect.get("estimates", []))
    if estimate_subjects != expected_estimates:
        failures.append(
            f"estimate subjects {estimate_subjects} != expected {expected_estimates}"
        )

    disclosures = spec.mode_notes + spec.unavailable
    for url in expect.get("discloses_unavailable", []):
        if not any(url in d for d in disclosures):
            failures.append(f"unavailable source {url} was not disclosed")

    pdf_valid = False
    pdf_detail = "not rendered (violations present)"
    if not violations:
        pdf = render_report_pdf(spec)
        pdf_valid, pdf_detail = validate_document("pdf", pdf)
        checks["pdf_bytes"] = len(pdf)
    checks["pdf_valid"] = pdf_valid
    if not pdf_valid:
        failures.append(f"generated PDF failed validation: {pdf_detail}")

    return {
        "name": name,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "search_listings": listings,
    }


def run_eval_set(path: str | Path) -> dict[str, Any]:
    import asyncio

    data = load_eval_set(path)
    corpus = data["corpus"]
    verdicts = [asyncio.run(run_eval_case(case, corpus)) for case in data["cases"]]
    passed = sum(1 for v in verdicts if v["passed"])
    return {
        "cases": verdicts,
        "passed": passed,
        "total": len(verdicts),
        "ok": passed == len(verdicts),
    }


__all__ = ["load_eval_set", "run_eval_case", "run_eval_set"]
