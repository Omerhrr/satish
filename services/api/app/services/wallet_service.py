"""Wallet service: process-local BDK provider + DB wallet registry.

The provider holds NO secrets at rest (public-descriptor persistence; in-memory
signing wallet only during unlock TTL). This layer owns:
- provider construction from settings (lazy, single instance),
- the user-facing Wallet/WalletAddress/WalletTransaction rows,
- ownership enforcement (every wallet_id access is checked against user_id),
- alias resolution for the address book (aliases are labels ONLY — the
  authorization digest binds the resolved address, so re-labeling can never
  redirect a signed transaction).
"""

from __future__ import annotations

import json
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from wallet_adapter import BdkWalletProvider, BitcoindRpc, Network, WalletNotFound
from xp_core.config import Settings
from xp_core.models.entities import User, Wallet, WalletAddress, WalletTransaction

_provider: BdkWalletProvider | None = None
_provider_lock = threading.Lock()


def get_provider(settings: Settings) -> BdkWalletProvider:
    """Lazily build the process-wide provider from settings."""
    global _provider
    with _provider_lock:
        if _provider is None:
            if settings.env in ("regtest", "testnet", "signet"):
                network = Network(settings.env)
            else:
                network = Network.REGTEST  # dev default; mainnet is release-gated
            rpc = None
            if settings.bitcoind_rpc_url:
                rpc = BitcoindRpc(
                    url=settings.bitcoind_rpc_url,
                    rpc_user=settings.bitcoind_rpc_user or "",
                    rpc_password=settings.bitcoind_rpc_password or "",
                )
            _provider = BdkWalletProvider(
                network=network,
                data_dir=settings.wallet_data_dir,
                rpc=rpc,
                fallback_fee_rate_sat_vb=settings.wallet_fallback_fee_rate_sat_vb,
                max_fee_rate_sat_vb=settings.wallet_max_fee_rate_sat_vb,
                unlock_ttl_seconds=settings.wallet_unlock_ttl_minutes * 60,
                default_word_count=settings.wallet_default_word_count,
            )
        return _provider


def descriptors_json(public_descriptor: str, change_public_descriptor: str) -> str:
    """Storage form for Wallet.public_descriptor_or_reference (no secrets)."""
    return json.dumps(
        {"external": public_descriptor, "internal": change_public_descriptor},
        separators=(",", ":"),
    )


def split_descriptors_json(blob: str | None) -> tuple[str | None, str | None]:
    if not blob:
        return None, None
    try:
        data = json.loads(blob)
        return data.get("external"), data.get("internal")
    except ValueError:
        return None, None


async def ensure_provider_open(
    session: AsyncSession, wallet: Wallet, settings: Settings
) -> BdkWalletProvider:
    """Re-open the process-local provider wallet if the API restarted.

    Uses only the stored PUBLIC descriptors; signing always requires a fresh
    unlock with the user's phrase.
    """
    provider = get_provider(settings)
    ext, chg = split_descriptors_json(wallet.public_descriptor_or_reference)
    if ext and chg:
        await provider.reopen(
            wallet.id,
            public_descriptor_external=ext,
            public_descriptor_internal=chg,
            label=wallet.label or "",
        )
    return provider


async def get_owned_wallet(session: AsyncSession, user: User, wallet_id: str) -> Wallet:
    """Fetch a wallet row the user owns; foreign ids look like missing ids."""
    row = (await session.execute(select(Wallet).where(Wallet.id == wallet_id))).scalar_one_or_none()
    if row is None or row.user_id != user.id:
        raise WalletNotFound("wallet not found")
    return row


async def record_transaction(
    session: AsyncSession,
    *,
    wallet_id: str,
    txid: str,
    transaction_type: str,
    amount_sats: int,
    fee_sats: int,
    metadata: dict[str, Any] | None = None,
) -> WalletTransaction:
    row = WalletTransaction(
        wallet_id=wallet_id,
        transaction_reference=txid,
        transaction_type=transaction_type,
        amount_sats=amount_sats,
        fee_sats=fee_sats,
        status="pending",
        raw_metadata=metadata or {},
    )
    session.add(row)
    await session.commit()
    return row


async def list_transactions(session: AsyncSession, wallet_id: str) -> list[WalletTransaction]:
    rows = (
        await session.execute(
            select(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet_id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return list(rows)


async def list_addresses(session: AsyncSession, wallet_id: str) -> list[WalletAddress]:
    rows = (
        await session.execute(
            select(WalletAddress)
            .where(WalletAddress.wallet_id == wallet_id)
            .order_by(WalletAddress.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return list(rows)


async def resolve_alias(
    session: AsyncSession, user: User, alias: str
) -> WalletAddress:
    """Address-book lookup; alias -> the address row (label semantics only)."""
    row = (
        await session.execute(
            select(WalletAddress).where(
                WalletAddress.user_id == user.id,
                WalletAddress.alias == alias,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise WalletNotFound("address alias not found")
    return row
