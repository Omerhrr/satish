"""Lightning adapter protocol + stub.

Selection criteria from the plan (lightning_policy): channel-state durability,
backup, recovery, force-close behavior, and liquidity management must be
reviewed before choosing an implementation (LDK / CLN / Eclair / lnd).
The node admin surface is NEVER exposed to the agent runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from wallet_adapter import Network


@dataclass(frozen=True, slots=True)
class Invoice:
    bolt11: str
    payment_hash: str
    amount_msat: int
    description: str
    expires_at_epoch: int


@dataclass(frozen=True, slots=True)
class PaymentStatus:
    payment_hash: str
    status: str  # pending | succeeded | failed
    fee_msat: int = 0
    preimage: str | None = None


class LightningProvider(Protocol):
    async def create_invoice(
        self, *, amount_msat: int, description: str, expiry_seconds: int
    ) -> Invoice: ...
    async def prepare_payment(self, bolt11: str) -> dict[str, Any]: ...
    async def submit_payment(self, payment_id: str) -> PaymentStatus: ...
    async def payment_status(self, payment_hash: str) -> PaymentStatus: ...


class LightningNotSelectedError(RuntimeError):
    pass


class StubLightningProvider:
    """Scaffold provider: contract shapes only, no node connectivity."""

    def __init__(self, network: Network = Network.REGTEST) -> None:
        if network is Network.MAINNET:
            raise ValueError("stub provider must never run against mainnet")
        self.network = network

    async def create_invoice(
        self, *, amount_msat: int, description: str, expiry_seconds: int
    ) -> Invoice:
        if amount_msat <= 0:
            raise ValueError("amount_msat must be positive")
        raise LightningNotSelectedError(
            "Lightning implementation pending channel-state/recovery review (phase 3+)"
        )

    async def prepare_payment(self, bolt11: str) -> dict[str, Any]:
        if not bolt11.startswith("ln"):
            raise ValueError("not a bolt11 invoice")
        return {"status": "not_prepared", "reason": "implementation pending"}

    async def submit_payment(self, payment_id: str) -> PaymentStatus:
        raise LightningNotSelectedError("implementation pending")

    async def payment_status(self, payment_hash: str) -> PaymentStatus:
        raise LightningNotSelectedError("implementation pending")
