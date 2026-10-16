"""Run the committed commerce evaluation set (phase-8 acceptance bars).

Usage:
    python scripts/commerce_eval.py [path-to-eval-set.json]

Exit code 0 iff every case passes its quality bars. The default set is the
committed tests/data/commerce_eval_set.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = REPO_ROOT / "tests" / "data" / "commerce_eval_set.json"


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT / "services" / "research-adapter"))
    sys.path.insert(0, str(REPO_ROOT / "services" / "commerce-adapter"))

    from commerce_adapter.eval import run_commerce_eval_set  # noqa: E402 (path set above)

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SET
    report = run_commerce_eval_set(path)
    print(json.dumps(report, indent=2, default=str))
    verdict = "PASS" if report["ok"] else "FAIL"
    print(f"\ncommerce eval: {verdict} - {report['passed']}/{report['total']} cases")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
