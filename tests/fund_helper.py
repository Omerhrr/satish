"""Offline funding helper: build a synthetic transaction that credits a wallet.

Used by API tests (no bitcoind): a structurally valid, non-coinbase tx with a
fabricated outpoint input and one P2WPKH output paying the wallet's address.
Imported into the BDK graph via provider.import_transaction, it behaves like
an unconfirmed UTXO for coin selection.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "wallet-adapter"))

import bdkpython as bdk
from wallet_adapter.bdk_provider import _bdk_network


def _le(n: int, size: int) -> bytes:
    return n.to_bytes(size, "little")


def build_funding_tx(address_str: str, amount_sats: int, seed: int = 1) -> str:
    """Raw hex of a synthetic tx paying ``amount_sats`` to ``address_str``."""
    address = bdk.Address(address_str, _bdk_network(__import__("wallet_adapter").Network.REGTEST))
    spk = address.script_pubkey().to_bytes()

    tx = bytearray()
    tx += _le(2, 4)                      # version 2
    tx += _le(1, 1)                      # input count = 1 (non-coinbase)
    tx += _le(seed * 7919 + 0xBEEF, 32)  # fabricated outpoint (non-null)
    tx += _le(0, 4)                      # vout 0
    tx += _le(0, 1)                      # empty scriptSig
    tx += b"\xff\xff\xff\xff"            # sequence
    tx += _le(1, 1)                      # output count = 1
    tx += _le(amount_sats, 8)            # value
    tx += _le(len(spk), 1)               # scriptPubKey len
    tx += spk
    tx += _le(0, 4)                      # locktime
    return bytes(tx).hex()


async def fund_wallet(provider, wallet_id: str, address: str, amount_sats: int, seed: int = 1) -> str:
    """Import a synthetic funding tx into the wallet graph; returns the tx hex."""
    raw_hex = build_funding_tx(address, amount_sats, seed=seed)
    await provider.import_transaction(wallet_id, raw_hex)
    return raw_hex
