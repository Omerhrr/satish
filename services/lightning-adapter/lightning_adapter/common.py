"""Shared primitives for the Lightning adapter (moved from the retired
server-side wallet adapter; the wallet now runs on the user's device)."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any


class Network(StrEnum):
    MAINNET = "mainnet"
    TESTNET = "testnet"
    SIGNET = "signet"
    REGTEST = "regtest"


def authorization_digest(payload: dict[str, Any]) -> str:
    """Canonical digest binding exactly what the user reviewed."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
