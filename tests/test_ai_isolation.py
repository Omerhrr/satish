"""Satish AI is fully isolated from the wallet: no wallet code, tools, data or wording."""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
AI_FILES = [
    *ROOT.glob("services/agent-adapter/dsh_adapter/*.py"),
    *ROOT.glob("services/research-adapter/research_adapter/*.py"),
    *ROOT.glob("services/commerce-adapter/commerce_adapter/*.py"),
    ROOT / "services/api/app/services/agent_service.py",
    ROOT / "services/api/app/services/research_tools.py",
]
WALLET_MODULES = ("xp_core.services.handles", "xp_core.services.onchain", "xp_core.services.wallet_alerts",
                  "app.api.v1.handles", "app.services.lightning_service", "lightning_adapter")


def test_ai_code_imports_no_wallet_modules():
    for f in AI_FILES:
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not n.startswith(WALLET_MODULES), f"{f.name} imports wallet module {n}"


def test_ai_tools_have_nothing_wallet_related():
    from dsh_adapter.tools import default_registry

    for d in default_registry().openai_tools():
        text = (d["function"]["name"] + " " + d["function"].get("description", "")).lower()
        for word in ("wallet", "seed", "private key", "sats", "lightning", "bitcoin", "@username"):
            assert word not in text, f"tool {d['function']['name']} mentions {word!r}"


def test_ai_instructions_dont_mention_wallet_internals():
    from dsh_adapter.client import SYSTEM_POLICY

    low = SYSTEM_POLICY.lower()
    for word in ("seed phrase", "private key", "signing", "bitcoin", "lightning", "@username"):
        assert word not in low
