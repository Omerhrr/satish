"""Lightning adapter (phase 4, decision D11).

lnd v0.21.4-beta selected via empirical two-node regtest drill; gRPC stubs
generated from the release's own protos (same manifest-pin philosophy as the
DSH decision, D8). The ``CannedLightningProvider`` carries lnd-identical
semantics in memory so every lifecycle/idempotency criterion is provable
offline — it is disclosed as canned wherever it is surfaced, never presented
as a real node.

The node admin surface is NEVER exposed to the agent runtime.
"""

from __future__ import annotations

from typing import Any, Protocol

from wallet_adapter import Network

from lightning_adapter.canned import (
    AuthorizationMismatch,
    CannedLightningProvider,
    Invoice,
    InvoiceExpired,
    InvoiceNotFound,
    LightningProviderError,
    NodeUnavailable,
    PaymentNotFound,
    PaymentRejected,
    PaymentStatus,
    PaymentUncertain,
    PreimageMismatch,
    PreparedPayment,
)
from lightning_adapter.state import (
    INVOICE_STATES,
    INVOICE_TRANSITIONS,
    PAYMENT_STATES,
    PAYMENT_TRANSITIONS,
    InvalidTransition,
    next_invoice_state,
    next_payment_state,
)

__all__ = [
    "INVOICE_STATES",
    "INVOICE_TRANSITIONS",
    "PAYMENT_STATES",
    "PAYMENT_TRANSITIONS",
    "AuthorizationMismatch",
    "CannedLightningProvider",
    "InvalidTransition",
    "Invoice",
    "InvoiceExpired",
    "InvoiceNotFound",
    "LightningNotSelectedError",
    "LightningProvider",
    "LightningProviderError",
    "LndLightningProvider",
    "NodeUnavailable",
    "PaymentNotFound",
    "PaymentRejected",
    "PaymentStatus",
    "PaymentUncertain",
    "PreimageMismatch",
    "PreparedPayment",
    "StubLightningProvider",
    "make_lightning_provider",
    "next_invoice_state",
    "next_payment_state",
]


class LightningProvider(Protocol):
    """Surface both providers implement (structural typing)."""

    implementation: str

    async def create_invoice(
        self, *, amount_msat: int, description: str, expiry_seconds: int
    ) -> Invoice: ...
    async def prepare_payment(self, bolt11: str) -> PreparedPayment: ...
    async def payment_status(self, payment_id: str) -> PaymentStatus: ...


class LightningNotSelectedError(RuntimeError):
    pass


class StubLightningProvider:
    """Scaffold provider kept for import compatibility (never constructed)."""

    implementation = "stub (scaffold; replaced by the phase-4 selection)"

    def __init__(self, network: Network = Network.REGTEST) -> None:
        if network is Network.MAINNET:
            raise ValueError("stub provider must never run against mainnet")
        self.network = network

    async def create_invoice(self, **_kw: Any) -> Invoice:
        raise LightningNotSelectedError("use CannedLightningProvider or lnd (D11)")

    async def prepare_payment(self, bolt11: str) -> PreparedPayment:
        raise LightningNotSelectedError("use CannedLightningProvider or lnd (D11)")

    async def payment_status(self, payment_id: str) -> PaymentStatus:
        raise LightningNotSelectedError("use CannedLightningProvider or lnd (D11)")


def make_lightning_provider(settings) -> CannedLightningProvider:
    """Sole construction point for the process-wide provider.

    ``settings.lightning_mode`` selects the implementation; ``lnd`` requires
    host/tls/macaroon (else LndConfigError) and is refused on mainnet like
    every other provider. The default is canned — dev/test semantics with
    honest disclosure at the API surface.
    """
    network = Network(settings.lightning_network)
    mode = settings.lightning_mode
    if mode == "canned":
        return CannedLightningProvider(
            network,
            base_fee_msat=settings.lightning_base_fee_msat,
            fee_ppm=settings.lightning_fee_ppm,
            max_fee_msat=settings.lightning_max_fee_msat,
        )
    if mode == "lnd":
        from lightning_adapter.lnd_provider import LndLightningProvider

        return LndLightningProvider(  # type: ignore[return-value]
            network,
            rpc_host=settings.lnd_rpc_host or "",
            tls_cert_path=settings.lnd_tls_cert_path or "",
            macaroon_path=settings.lnd_macaroon_path or "",
            max_fee_msat=settings.lightning_max_fee_msat,
            base_fee_msat=settings.lightning_base_fee_msat,
            fee_ppm=settings.lightning_fee_ppm,
        )
    raise ValueError(f"unknown lightning mode {mode!r} (canned | lnd)")
