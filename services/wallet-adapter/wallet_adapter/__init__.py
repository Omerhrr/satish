"""Wallet adapter protocol + signing boundary.

Design rules from the plan (wallet_and_security):
- The AI agent NEVER receives seed material or arbitrary signing authority.
- Signing happens through an explicit, user-confirmed SigningBoundary.
- The concrete wallet library is chosen after a documented threat-model and
  integration spike; this protocol keeps that choice replaceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class Network(StrEnum):
    MAINNET = "mainnet"
    TESTNET = "testnet"
    SIGNET = "signet"
    REGTEST = "regtest"


@dataclass(frozen=True, slots=True)
class PreparedTransaction:
    """A fully described, unsigned transaction pending user review."""

    wallet_id: str
    network: Network
    destination: str
    amount_sats: int
    fee_sats: int
    total_sats: int
    psbt_or_reference: str
    warnings: list[str]


class SigningBoundary(Protocol):
    """The ONLY path to signing. Implementations must require explicit,
    fresh, user-scoped authorization; agent identities are rejected."""

    async def sign(
        self, prepared: PreparedTransaction, *, authorization_digest: str, actor: str
    ) -> str: ...


class WalletProvider(Protocol):
    """Replaceable wallet implementation surface (non-secret metadata only
    ever flows back to the application)."""

    async def create_wallet_metadata(self, *, network: Network, label: str) -> dict[str, Any]: ...
    async def derive_address(self, wallet_id: str, *, index: int = 0) -> str: ...
    async def get_balance_sats(self, wallet_id: str) -> int: ...
    async def prepare_transaction(
        self, wallet_id: str, *, destination: str, amount_sats: int, fee_rate_sat_vb: int
    ) -> PreparedTransaction: ...
    async def broadcast(self, signed_tx: str) -> str: ...


class NotYetSelectedError(RuntimeError):
    """Raised by stubs until the wallet library decision spike (phase 3) lands."""


# -- phase-3: BDK-backed provider (decision D10) ---------------------------------

from wallet_adapter.bdk_provider import (  # noqa: E402 - protocol classes must be defined first
    AgentSigningForbidden,
    AuthorizationMismatch,
    BalanceInfo,
    BdkWalletProvider,
    BroadcastRejected,
    BroadcastUncertain,
    CreatedWallet,
    InsufficientFunds,
    InvalidAddress,
    InvalidAmount,
    InvalidMnemonic,
    MnemonicMismatch,
    NetworkMismatch,
    PreparedTransactionNotFound,
    SignedTransaction,
    SigningLocked,
    TxStatus,
    UnlockInfo,
    WalletAlreadyExists,
    WalletError,
    WalletNotFound,
    authorization_digest,
)
from wallet_adapter.rpc import BitcoindRpc, RpcError, RpcRejected, RpcUnavailable  # noqa: E402 - protocol classes must be defined first

__all__ = [
    "AgentSigningForbidden",
    "AuthorizationMismatch",
    "BalanceInfo",
    "BdkWalletProvider",
    "BitcoindRpc",
    "BroadcastRejected",
    "BroadcastUncertain",
    "CreatedWallet",
    "InsufficientFunds",
    "InvalidAddress",
    "InvalidAmount",
    "InvalidMnemonic",
    "MnemonicMismatch",
    "Network",
    "NetworkMismatch",
    "NotYetSelectedError",
    "PreparedTransaction",
    "PreparedTransactionNotFound",
    "RegtestStubProvider",
    "RpcError",
    "RpcRejected",
    "RpcUnavailable",
    "SignedTransaction",
    "SigningBoundary",
    "SigningLocked",
    "TxStatus",
    "UnlockInfo",
    "WalletAlreadyExists",
    "WalletError",
    "WalletNotFound",
    "WalletProvider",
    "authorization_digest",
]


class RegtestStubProvider:
    """Scaffold implementation that validates shapes but performs no custody.

    It exists so API/UX work can proceed on regtest-shaped contracts while the
    real library integration (BDK / bitcoind / LDK decision) is pending.
    """

    def __init__(self, network: Network = Network.REGTEST) -> None:
        if network is Network.MAINNET:
            raise ValueError("stub provider must never run against mainnet")
        self.network = network

    async def create_wallet_metadata(self, *, network: Network, label: str) -> dict[str, Any]:
        return {
            "status": "not_created",
            "reason": "wallet library pending threat-model + integration spike (phase 3)",
            "network": network.value,
            "label": label,
        }

    async def derive_address(self, wallet_id: str, *, index: int = 0) -> str:
        raise NotYetSelectedError("address derivation pending wallet library selection")

    async def get_balance_sats(self, wallet_id: str) -> int:
        return 0

    async def prepare_transaction(
        self, wallet_id: str, *, destination: str, amount_sats: int, fee_rate_sat_vb: int
    ) -> PreparedTransaction:
        if amount_sats <= 0:
            raise ValueError("amount_sats must be positive")
        if fee_rate_sat_vb <= 0:
            raise ValueError("fee_rate must be positive")
        if not destination or len(destination) < 14:
            raise ValueError("destination must be a valid address")
        # No real construction yet — this is a validated contract shape.
        vsize_estimate = 141  # single-input single-output P2WPKH approximation
        fee = vsize_estimate * fee_rate_sat_vb
        return PreparedTransaction(
            wallet_id=wallet_id,
            network=self.network,
            destination=destination,
            amount_sats=amount_sats,
            fee_sats=fee,
            total_sats=amount_sats + fee,
            psbt_or_reference="",
            warnings=["stub: transaction construction requires the phase-3 wallet library"],
        )

    async def broadcast(self, signed_tx: str) -> str:
        raise NotYetSelectedError("broadcast pending wallet library selection")
