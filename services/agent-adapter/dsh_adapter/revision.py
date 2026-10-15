"""Pinned DSH revision — loader, validator, and cost estimator.

The pin (dsh_revision.json) is the single source of truth for which
upstream DeepSeek API surface this adapter is tested against (plan:
dsh_integration.requirements #1 — "Pin a tested upstream DSH revision";
architecture logical_components #5 security note — "Pin a tested DSH
revision and document the integration contract").

Editing the manifest is a deliberate act: tests/test_dsh_revision.py
hard-codes the manifest checksum, so any drift must consciously update
the test (two-person-rule style gate).

Discontinued legacy model names are rejected at load time so a stale
XP_DEEPSEEK_MODEL can never silently route to a dead alias.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from xp_core.logging import get_logger

log = get_logger(__name__)

MANIFEST_PATH = Path(__file__).parent / "dsh_revision.json"

# Statuses that must never reach the wire.
HARD_DEAD_STATUSES = {"discontinued"}


class RevisionError(RuntimeError):
    """The pinned revision manifest is missing, malformed, or violates policy."""


class LegacyModelError(RevisionError):
    """A discontinued/retired legacy model name was requested."""


def canonical_checksum(path: Path = MANIFEST_PATH) -> str:
    """sha256 over canonical JSON (sorted keys, compact separators)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class PinnedRevision:
    """Typed accessor over the validated pin manifest."""

    def __init__(self, data: dict[str, Any], checksum: str) -> None:
        self._data = data
        self.checksum = checksum

    # -- identity ------------------------------------------------------------
    @property
    def revision_id(self) -> str:
        return self._data["revision_id"]

    @property
    def pinned_at(self) -> str:
        return self._data["pinned_at"]

    @property
    def base_url(self) -> str:
        return self._data["provider"]["base_url"]

    # -- models ----------------------------------------------------------------
    @property
    def primary_model(self) -> str:
        return self._data["models"]["primary"]["name"]

    @property
    def heavy_model(self) -> str:
        return self._data["models"]["heavy"]["name"]

    def model_entry(self, name: str) -> dict[str, Any]:
        for entry in self._data["models"].values():
            if entry["name"] == name:
                return entry
        raise RevisionError(f"model {name!r} is not part of pinned revision {self.revision_id}")

    def validate_model(self, name: str) -> str:
        """Resolve a configured model name against the pin; reject hard-dead aliases."""
        if name == self.primary_model or name == self.heavy_model:
            return name
        for alias in self._data.get("legacy_aliases", []):
            if alias["name"] == name:
                if alias["status"] in HARD_DEAD_STATUSES or alias["status"].startswith("discontinued"):
                    raise LegacyModelError(
                        f"model {name!r} is discontinued upstream "
                        f"({alias['status']}); pinned models: "
                        f"{self.primary_model} / {self.heavy_model}"
                    )
                # retired-but-served aliases: allowed, logged loudly
                log.warning(
                    "dsh_legacy_model_alias",
                    requested=name,
                    status=alias["status"],
                    note=alias["note"],
                )
                return name
        raise RevisionError(
            f"model {name!r} is not in pinned revision {self.revision_id}; "
            f"allowed: {self.primary_model}, {self.heavy_model}, or a "
            f"retired-but-served alias listed in the manifest"
        )

    # -- limits / contract -------------------------------------------------------
    @property
    def limits(self) -> dict[str, Any]:
        return self._data["adapter_contract"]["adapter_limits"]

    @property
    def thinking_default(self) -> bool:
        return self._data["models"]["primary"]["thinking_mode_default"]

    # -- cost ---------------------------------------------------------------------
    def estimate_cost_usd(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int = 0,
        peak: bool = False,
    ) -> float | None:
        """Deterministic cost estimate from pinned pricing (off-peak unless peak=True).

        Returns None when the model has no pinned pricing (caller should
        surface that honestly rather than guess).
        """
        try:
            entry = self.model_entry(model)
            pricing = entry["pricing_usd_per_1m_tokens"]
        except (RevisionError, KeyError):
            return None
        slot = "peak" if peak else "off_peak"
        cache_miss_tokens = max(0, prompt_tokens - cache_hit_tokens)
        cost = (
            cache_hit_tokens * pricing["input_cache_hit"][slot] / 1_000_000
            + cache_miss_tokens * pricing["input_cache_miss"][slot] / 1_000_000
            + completion_tokens * pricing["output"][slot] / 1_000_000
        )
        return round(cost, 6)


def load_revision(path: Path = MANIFEST_PATH) -> PinnedRevision:
    """Load and structurally validate the pin manifest."""
    if not path.exists():
        raise RevisionError(f"DSH revision manifest missing at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RevisionError(f"DSH revision manifest is not valid JSON: {exc}") from exc

    required_top = {"manifest_version", "revision_id", "pinned_at", "provider", "models", "adapter_contract"}
    missing = required_top - data.keys()
    if missing:
        raise RevisionError(f"DSH revision manifest missing keys: {sorted(missing)}")
    for slot in ("primary", "heavy"):
        entry = data["models"].get(slot, {})
        for field in ("name", "upstream_version", "pricing_usd_per_1m_tokens"):
            if field not in entry:
                raise RevisionError(f"models.{slot} missing {field!r}")

    rev = PinnedRevision(data, canonical_checksum(path))
    log.info(
        "dsh_revision_loaded",
        revision_id=rev.revision_id,
        pinned_at=rev.pinned_at,
        checksum=rev.checksum[:12],
        primary=rev.primary_model,
    )
    return rev
