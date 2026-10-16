"""Deterministic agent output evaluation (phase 6, deliverable: Agent output
evaluation).

The evaluation runs in backend code - never in the model - so its verdicts
are reproducible and auditable. It scores three axes from the execution
contract (agent_and_tooling: "Evaluate completeness, source quality, and
consistency"):

- completeness: did the run produce the deliverable, and how much of the
  plan actually executed?
- provenance:   do factual/research runs carry sources and citations
  (research_quality: "Cite claims in generated reports")?
- consistency:  cheap structural checks - duplicate tool steps, empty
  results passed off as findings, contradiction placeholders.

The result is a small dict meant for persistence in the task event stream
and the final report. Heuristics are intentionally conservative: the score
describes the artifact's structure, not its truth - limitations are stated
in the notes.
"""

from __future__ import annotations

from typing import Any


def evaluate_run(
    *,
    report: dict[str, Any],
    plan: dict[str, Any],
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate a finished run. Deterministic; same inputs -> same verdict."""
    notes: list[str] = []

    # completeness
    planned = len(plan.get("plan", []) or [])
    completed = sum(1 for s in steps if s.get("status") == "completed")
    deliverable = report.get("deliverable") or plan.get("deliverable")
    has_deliverable = bool(deliverable and str(deliverable).strip())
    if not has_deliverable:
        notes.append("no deliverable was produced")
    if planned and completed < planned:
        notes.append(
            f"{completed}/{planned} planned steps completed"
        )
    completeness = {
        "has_deliverable": has_deliverable,
        "steps_completed": completed,
        "steps_planned": planned,
        "score": round(
            (0.5 if has_deliverable else 0.0) + (0.5 * completed / planned if planned else 0.5),
            3,
        ),
    }

    # provenance
    sources = report.get("sources") or []
    research_steps = [
        s
        for s in steps
        if s.get("tool") in ("web.search", "web.fetch_page") and s.get("status") == "completed"
    ]
    if research_steps and not sources:
        notes.append("research steps ran but no sources were recorded")
    provenance = {
        "source_count": len(sources),
        "research_steps": len(research_steps),
        "score": 1.0 if not research_steps or sources else 0.0,
    }

    # consistency
    tool_seq = [s.get("tool") for s in steps if s.get("tool")]
    duplicates = len(tool_seq) - len(set(tool_seq))
    empty_results = sum(
        1
        for s in steps
        if s.get("status") == "completed"
        and isinstance(s.get("result"), dict)
        and s["result"].get("status") in ("stub", "not_implemented")
    )
    if duplicates:
        notes.append(f"{duplicates} duplicate tool steps in one plan")
    if empty_results:
        notes.append(
            f"{empty_results} step results are stubs - findings are placeholders, "
            "not observations (research_quality: do not fabricate)"
        )
    consistency = {
        "duplicate_steps": duplicates,
        "stub_results": empty_results,
        "score": round(max(0.0, 1.0 - 0.25 * duplicates - 0.1 * empty_results), 3),
    }

    overall = round(
        0.4 * completeness["score"] + 0.3 * provenance["score"] + 0.3 * consistency["score"], 3
    )
    return {
        "completeness": completeness,
        "provenance": provenance,
        "consistency": consistency,
        "score": overall,
        "notes": notes,
        "limitations": [
            "structural evaluation only - this does not verify factual truth; "
            "sources and claims remain the user's responsibility to review"
        ],
    }


__all__ = ["evaluate_run"]
