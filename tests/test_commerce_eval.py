"""Phase-8 acceptance: the committed repeatable commerce evaluation set.

Run by ``make commerce-eval`` and here as pytest: every case must pass its
quality bars, and the set must be reproducible (same inputs -> same
verdicts) — that is what makes it the regression harness for the commerce
pipeline.
"""

from __future__ import annotations

from pathlib import Path

from commerce_adapter.eval import load_commerce_eval_set, run_commerce_eval_set

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMERCE_SET = REPO_ROOT / "tests" / "data" / "commerce_eval_set.json"


def test_commerce_eval_set_passes():
    report = run_commerce_eval_set(COMMERCE_SET)
    assert report["ok"], [
        (c["name"], c["failures"]) for c in report["cases"] if not c["passed"]
    ]
    assert report["passed"] == report["total"] == 7


def test_commerce_eval_set_is_reproducible():
    first = run_commerce_eval_set(COMMERCE_SET)
    second = run_commerce_eval_set(COMMERCE_SET)
    assert first == second, "the committed set must be deterministic"


def test_commerce_eval_set_covers_acceptance_bars():
    data = load_commerce_eval_set(COMMERCE_SET)
    names = {case["name"] for case in data["cases"]}
    assert {
        "scoring_transparency_and_config",      # factors visible + config echoed
        "mixed_currency_spread_excluded",       # no fabricated exchange rates
        "supplier_comparison_conflict",         # cited supplier comparison
        "ad_library_no_performance_claims",     # no invented ad performance
        "ad_library_zero_results_is_honest",    # only permitted sources searched
        "vehicle_spec_check",                   # vehicle auction workflow
        "landed_cost_typing",                   # asking/estimate/observed/assumption
    } <= names
    meta = data["_meta"]
    assert meta["phase"] == 8
    assert len(data["corpus"]) >= 7


def test_commerce_eval_missing_file_is_loud(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        run_commerce_eval_set(tmp_path / "missing.json")
