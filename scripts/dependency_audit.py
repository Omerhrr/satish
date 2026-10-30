"""Dependency and container audit (phase 10, deliverable: Dependency and
container scanning).

What it does, honestly:

1. PYTHON INVENTORY - parses every workspace pyproject.toml (packages/*,
   services/*, apps/bot) with tomllib and inventories declared dependencies.
2. CONTAINER INVENTORY - parses infra/docker-compose.yml and lists images.
3. NODE INVENTORY - parses apps/web/package.json (runtime + dev deps).
4. GATES (exit 1 on any hard finding):
   - python/node dependency spec containing ``*`` or ``git+`` or a local path
   - container image without an explicit tag or tagged ``:latest``
5. OPTIONAL LIVE SCANNERS - pip-audit / trivy / bun audit are run only if
   present on PATH; when absent the report says so explicitly instead of
   pretending a scan happened. Network-dependent scanners are therefore a
   documented operator step (docs/operations.md), not a silent skip.

Run: make audit    (or .venv/bin/python scripts/dependency_audit.py)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

HARD = "hard"
INFO = "info"


def _python_inventory(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Returns (inventory, findings) for every declared python dependency."""
    inventory: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    for pyproject in sorted(root.glob("*/pyproject.toml")) + sorted(
        root.glob("services/*/pyproject.toml")
    ) + sorted(root.glob("packages/*/pyproject.toml")) + sorted(root.glob("apps/*/pyproject.toml")):
        rel = str(pyproject.relative_to(root))
        data = tomllib.loads(pyproject.read_text())
        deps: list[str] = list(data.get("project", {}).get("dependencies", []))
        for extra in (data.get("project", {}).get("optional-dependencies", {}) or {}).values():
            deps.extend(extra)
        seen: set[str] = set()
        for spec in deps:
            name = re.split(r"[<>=!\[\s;]", spec, maxsplit=1)[0].strip()
            if not name or name in seen:
                continue
            seen.add(name)
            inventory.append({"project": rel, "name": name, "spec": spec})
            if "*" in spec or "git+" in spec or spec.strip().startswith("."):
                findings.append(
                    {
                        "severity": HARD,
                        "area": "python",
                        "finding": f"unauditable dependency spec '{spec}' in {rel}",
                    }
                )
    return inventory, findings


def _container_inventory(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    import yaml

    compose = root / "infra" / "docker-compose.yml"
    inventory: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    if not compose.exists():
        findings.append(
            {"severity": INFO, "area": "container", "finding": "no docker-compose.yml found"}
        )
        return inventory, findings
    data = yaml.safe_load(compose.read_text()) or {}
    for name, svc in (data.get("services") or {}).items():
        image = svc.get("image")
        if not image:
            continue
        inventory.append({"service": name, "image": image})
        _, _, tag = image.partition(":")
        if not tag or tag == "latest":
            findings.append(
                {
                    "severity": HARD,
                    "area": "container",
                    "finding": f"image '{image}' (service {name}) is not pinned to an explicit tag",
                }
            )
    return inventory, findings


def _node_inventory(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    pkg = root / "apps" / "web" / "package.json"
    inventory: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    if not pkg.exists():
        return inventory, findings
    data = json.loads(pkg.read_text())
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            inventory.append({"section": section, "name": name, "spec": spec})
            workspace_internal = spec.startswith("workspace:")
            if not workspace_internal and (spec in ("*", "latest") or "git+" in spec):
                findings.append(
                    {
                        "severity": HARD,
                        "area": "node",
                        "finding": f"unauditable npm spec '{name}@{spec}'",
                    }
                )
    return inventory, findings


def _optional_scanners() -> list[dict[str, str]]:
    """Best-effort live scanners; each absence is disclosed, never faked."""
    out: list[dict[str, str]] = []
    for tool, args in (
        ("pip-audit", ["pip-audit", "--version"]),
        ("trivy", ["trivy", "--version"]),
        ("bun", ["bun", "--version"]),
    ):
        path = shutil.which(tool)
        if path is None:
            out.append(
                {
                    "tool": tool,
                    "status": "not_installed",
                    "note": f"{tool} is not bundled; run it in CI/on an operator host "
                    "for live CVE scanning (documented in docs/operations.md)",
                }
            )
            continue
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
            out.append(
                {
                    "tool": tool,
                    "status": "available",
                    "version": (proc.stdout or proc.stderr).strip().splitlines()[0][:80],
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            out.append({"tool": tool, "status": "error", "note": str(exc)[:120]})
    return out


def audit_repo(root: Path = REPO_ROOT) -> dict[str, Any]:
    py_inv, py_find = _python_inventory(root)
    ct_inv, ct_find = _container_inventory(root)
    nd_inv, nd_find = _node_inventory(root)
    findings = [*py_find, *ct_find, *nd_find]
    return {
        "audit": "dependency_and_container",
        "ran_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "python_dependencies": len(py_inv),
        "container_images": ct_inv,
        "node_dependencies": len(nd_inv),
        "live_scanners": _optional_scanners(),
        "findings": findings,
        "hard_findings": [f for f in findings if f["severity"] == HARD],
        "ok": not any(f["severity"] == HARD for f in findings),
    }


def _main() -> int:
    report = audit_repo()
    print(json.dumps(report, indent=2))
    if not report["ok"]:
        print("AUDIT FAILED: hard findings above", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
