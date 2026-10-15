"""The repeatable research evaluation set (phase-7 acceptance #5).

These tests ARE the acceptance harness: they run the committed eval set and
assert both per-case verdicts and the set's coverage of the quality bars.
If someone weakens the pipeline, the set fails here and via
`make research-eval`.
"""

from __future__ import annotations

from pathlib import Path

from research_adapter.eval import load_eval_set, run_eval_case, run_eval_set

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SET = REPO_ROOT / "tests" / "data" / "research_eval_set.json"


def test_eval_set_is_committed_and_structured():
    data = load_eval_set(EVAL_SET)
    assert len(data["corpus"]) >= 4, "corpus must be non-trivial"
    names = [c["name"] for c in data["cases"]]
    assert len(names) >= 5
    assert len(set(names)) == len(names), "case names must be unique"


def test_every_case_passes_its_quality_bars():
    report = run_eval_set(EVAL_SET)
    assert report["ok"], [
        (c["name"], c["failures"]) for c in report["cases"] if not c["passed"]
    ]
    assert report["passed"] == report["total"]


async def test_set_covers_the_quality_bars():
    """The set must actually exercise: conflicts, unavailable disclosure,
    estimate typing, citation gates, and the honest-empty case."""
    data = load_eval_set(EVAL_SET)
    corpus = data["corpus"]
    by_name = {c["name"]: c for c in data["cases"]}
    assert any(c["expect"]["conflicts"] for c in data["cases"]), "no conflict case"
    assert any(c["expect"]["gaps"] for c in data["cases"]), "no gap case"
    assert any(c["expect"]["estimates"] for c in data["cases"]), "no estimate case"
    assert any(c["expect"]["discloses_unavailable"] for c in data["cases"]), "no unavailable case"

    # the honest-empty case: no sources -> zero claims, report still valid
    verdict = await run_eval_case(by_name["no_sources_honest_empty_report"], corpus)
    assert verdict["passed"] and verdict["checks"]["sources_fetched_ok"] == 0
    assert verdict["checks"]["claims_all_cited"]


def test_reports_render_valid_pdfs():
    report = run_eval_set(EVAL_SET)
    pdfs = [c["checks"].get("pdf_valid") for c in report["cases"]]
    assert all(pdfs), "every rendered report must validate"
