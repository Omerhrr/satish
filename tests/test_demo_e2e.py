"""Phase-11 acceptance: the committed end-to-end demo is reproducible.

`make demo` runs scripts/demo_e2e.py; this test runs the same function so
the demo cannot silently drift from reality. Every step carries its own
assertions inside the script; here we verify the report structure and that
the honesty notes stay pinned (they are the anti-overclaim guardrail).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


async def test_demo_e2e_passes_and_stays_honest():
    import demo_e2e

    report = await demo_e2e.run_demo(lambda _msg: None)
    assert report["ok"] is True
    steps = [s["step"] for s in report["steps"]]
    assert steps == [
        "health",
        "session",
        "xp_grant",
        "wallet_self_custody",
        "purchase",
        "settlement",
        "task_created",
        "agent_run",
        "task_result",
        "artifact_pdf",
        "ops",
    ]
    # double-credit refusal is the core money claim; pin it forever
    settlement = next(s for s in report["steps"] if s["step"] == "settlement")
    assert settlement["credited"] is True
    assert settlement["replay_credited"] is False
    assert settlement["double_credit_possible"] is False
    # anti-overclaim: the demo must keep disclosing its canned surfaces
    notes = " ".join(report["honesty_notes"])
    assert "canned" in notes
    assert "lightning-drill" in notes and "device" in notes
    assert "stub mode" in notes
