"""BDK-backed on-chain wallet provider (phase-3, decision D10).

Library: bdkpython (BDK 1.x core, UniFFI bindings) — proven end-to-end on
bitcoin regtest in scripts/regtest_proof.py before this integration.

Custody model (honesty rules from wallet_and_security):
- Persisted wallet state uses PUBLIC descriptors ONLY: the per-wallet sqlite
  (BDK persister) never contains private key material or seed words.
- Signing happens in an in-memory wallet built at UNLOCK from the user's
  recovery phrase. The phrase is held in process memory for the unlock TTL,
  never written to disk, DB, logs, or task context, and dropped on lock/expiry.
- The signing boundary rejects agent actors outright and requires a fresh
  unlock plus an authorization digest binding the reviewed transaction.
- The unsigned PSBT is built by the persisted (public) wallet — it owns the
  UTXO graph — and is signed by the in-memory private wallet, whose derivation
  coverage is synced to the persisted wallet's indexes at unlock time.

This is a server-side signing-vault design, NOT browser-side signing and NOT
a claim of hardware-wallet-grade protection; the UI copy and docs must say so.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bdkpython as bdk

from wallet_adapter.rpc import BitcoindRpc, RpcError, RpcUnavailable

from . import Network, PreparedTransaction

_DUST_SATS = 546
_WORD_COUNT_ORDER = (12, 15, 18, 21, 24)


def _word_count(count: int) -> bdk.WordCount:
    """Map a word count to the BDK enum (values are positional, not names)."""
    try:
        return bdk.WordCount(_WORD_COUNT_ORDER.index(count))
    except ValueError as exc:
        raise InvalidMnemonic(f"unsupported word count {count}") from exc


# -- errors ---------------------------------------------------------------------


class WalletError(RuntimeError):
    """Base class for provider failures (API layer maps these to HTTP)."""


class WalletNotFound(WalletError): ...
class WalletAlreadyExists(WalletError): ...
class InvalidAddress(WalletError): ...
class NetworkMismatch(WalletError): ...
class InvalidAmount(WalletError): ...
class InsufficientFunds(WalletError): ...
class InvalidMnemonic(WalletError): ...
class MnemonicMismatch(WalletError): ...
class SigningLocked(WalletError): ...
class AgentSigningForbidden(WalletError): ...
class AuthorizationMismatch(WalletError): ...
class PreparedTransactionNotFound(WalletError): ...
class BroadcastRejected(WalletError): ...
class BroadcastUncertain(WalletError):
    """The node could not be reached during broadcast; outcome unknown."""


# -- data types -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BalanceInfo:
    confirmed_sats: int
    unconfirmed_sats: int
    total_sats: int


@dataclass(frozen=True, slots=True)
class CreatedWallet:
    wallet_id: str
    network: Network
    label: str
    public_descriptor: str  # xpub-based, safe to store/display
    change_public_descriptor: str  # xpub-based internal keychain
    first_address: str
    mnemonic_once: str | None  # ONE-TIME display; None for restore flows


@dataclass(frozen=True, slots=True)
class SignedTransaction:
    tx_hex: str
    txid: str
    vsize: int
    fee_sats: int


@dataclass(frozen=True, slots=True)
class UnlockInfo:
    wallet_id: str
    expires_at_epoch: float


@dataclass(frozen=True, slots=True)
class TxStatus:
    txid: str
    state: str  # unknown | mempool | confirmed
    confirmations: int
    block_height: int | None


# -- helpers --------------------------------------------------------------------

_NETWORK_ORDINALS = ["BITCOIN", "TESTNET", "TESTNET4", "SIGNET", "REGTEST"]


def _bdk_network(network: Network) -> bdk.Network:
    return bdk.Network(_NETWORK_ORDINALS.index(network.value.upper()))


def _bdk_network_kind(network: Network) -> bdk.NetworkKind:
    return bdk.NetworkKind.MAIN if network is Network.MAINNET else bdk.NetworkKind.TEST


def _parses_on_other_network(destination: str, own: Network) -> bool:
    """True if the address is structurally valid for a network other than ``own``."""
    for name in _NETWORK_ORDINALS:
        net = bdk.Network(_NETWORK_ORDINALS.index(name))
        try:
            bdk.Address(destination, net)
        except Exception as exc:  # noqa: BLE001 — opaque uniffi errors by design
            _ = exc  # parse failure on this network: try the next one
            continue
        if net != _bdk_network(own):
            return True
    return False


def _descriptor_checksum(desc: bdk.Descriptor) -> str:
    # to_string_with_secret() = wpkh(...)#checksum — checksum is the suffix.
    return desc.to_string_with_secret().rsplit("#", 1)[-1]


def _public_descriptor_string(desc: bdk.Descriptor) -> str:
    return desc.as_public().to_string_with_secret().split("#")[0]


def authorization_digest(payload: dict[str, Any]) -> str:
    """Canonical digest binding exactly what the user reviewed."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class _WalletHandle:
    """Runtime state for one persisted (public-descriptor) wallet."""

    wallet_id: str
    network: Network
    label: str
    descriptor: bdk.Descriptor  # private-capable descriptor object (xprv form)
    wallet: bdk.Wallet  # built from PUBLIC descriptors + sqlite persister
    persister: bdk.Persister


@dataclass
class _Unlocked:
    private_wallet: bdk.Wallet
    expires_at: float


@dataclass
class _Pending:
    wallet_id: str
    prepared: PreparedTransaction
    digest: str
    psbt: bdk.Psbt


# -- provider ---------------------------------------------------------------------


class BdkWalletProvider:
    """Real on-chain provider: BDK for keys/PSBT/signing, bitcoind for chain I/O.

    Implements the WalletProvider protocol plus the phase-3 extended surface
    (create/restore/unlock/lock/sign/status). CPU-bound BDK calls run in a
    worker thread to keep the event loop responsive.
    """

    def __init__(
        self,
        *,
        network: Network,
        data_dir: Path | str,
        rpc: BitcoindRpc | None = None,
        fallback_fee_rate_sat_vb: int = 2,
        max_fee_rate_sat_vb: int = 50,
        unlock_ttl_seconds: int = 600,
        default_word_count: int = 24,
    ) -> None:
        if network is Network.MAINNET:
            raise ValueError(
                "mainnet operation is gated on the security-review release gate; "
                "override this guard explicitly only after that gate passes"
            )
        self.network = network
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.rpc = rpc
        self.fallback_fee_rate_sat_vb = fallback_fee_rate_sat_vb
        self.max_fee_rate_sat_vb = max_fee_rate_sat_vb
        self.unlock_ttl_seconds = unlock_ttl_seconds
        self.default_word_count = default_word_count
        self._wallets: dict[str, _WalletHandle] = {}
        self._unlocked: dict[str, _Unlocked] = {}
        self._pending: dict[str, _Pending] = {}
        self._lock = asyncio.Lock()

    # -- construction helpers ---------------------------------------------------

    def _descriptors_from_mnemonic(
        self, mnemonic: bdk.Mnemonic, password: str
    ) -> tuple[bdk.Descriptor, bdk.Descriptor]:
        sk = bdk.DescriptorSecretKey(
            network_kind=_bdk_network_kind(self.network), mnemonic=mnemonic, password=password
        )
        external = bdk.Descriptor.new_bip84(sk, bdk.KeychainKind.EXTERNAL, _bdk_network_kind(self.network))
        internal = bdk.Descriptor.new_bip84(sk, bdk.KeychainKind.INTERNAL, _bdk_network_kind(self.network))
        return external, internal

    def _sqlite_path(self, wallet_id: str) -> Path:
        return self.data_dir / f"wallet-{wallet_id}.sqlite"

    def _create_persisted_wallet(
        self, wallet_id: str, ext: bdk.Descriptor, chg: bdk.Descriptor
    ) -> tuple[bdk.Wallet, bdk.Persister]:
        persister = bdk.Persister.new_sqlite(str(self._sqlite_path(wallet_id)))
        wallet = bdk.Wallet.create_with_params(
            descriptor=ext.as_public(),
            change_descriptor=chg.as_public(),
            network=_bdk_network(self.network),
            persister=persister,
            params=bdk.CreateParams(genesis_hash=None, lookahead=25, use_spk_cache=False),
        )
        wallet.persist(persister)
        return wallet, persister

    def _load_persisted_wallet(
        self, wallet_id: str, ext: bdk.Descriptor, chg: bdk.Descriptor
    ) -> tuple[bdk.Wallet, bdk.Persister]:
        persister = bdk.Persister.new_sqlite(str(self._sqlite_path(wallet_id)))
        wallet = bdk.Wallet.load_with_params(
            descriptor=ext.as_public(),
            change_descriptor=chg.as_public(),
            persister=persister,
            params=bdk.LoadParams(
                check_network=_bdk_network(self.network),
                check_genesis_hash=None,
                lookahead=25,
                use_spk_cache=False,
            ),
        )
        return wallet, persister

    def _handle(self, wallet_id: str) -> _WalletHandle:
        handle = self._wallets.get(wallet_id)
        if handle is None:
            raise WalletNotFound(f"wallet {wallet_id} is not open in this process")
        return handle

    # -- create / restore ---------------------------------------------------------

    async def create_wallet(
        self, *, label: str = "", word_count: int | None = None, password: str = ""
    ) -> CreatedWallet:
        """Fresh wallet. The mnemonic is returned ONCE through this call only."""
        async with self._lock:
            wc = word_count or self.default_word_count
            if wc not in _WORD_COUNT_ORDER:
                raise InvalidMnemonic(f"unsupported word count {wc}")
            mnemonic = await asyncio.to_thread(bdk.Mnemonic, word_count=_word_count(wc))
            ext, chg = await asyncio.to_thread(self._descriptors_from_mnemonic, mnemonic, "")
            # deterministic id from the descriptor id: same phrase -> same wallet id,
            # so create/restore semantics agree and re-open is idempotent
            wallet_id = str(ext.descriptor_id())
            wallet, persister = await asyncio.to_thread(
                self._create_persisted_wallet, wallet_id, ext, chg
            )
            self._wallets[wallet_id] = _WalletHandle(
                wallet_id=wallet_id, network=self.network, label=label,
                descriptor=ext, wallet=wallet, persister=persister,
            )
            first = str(wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address)
            wallet.persist(persister)
            return CreatedWallet(
                wallet_id=wallet_id, network=self.network, label=label,
                public_descriptor=_public_descriptor_string(ext),
                change_public_descriptor=_public_descriptor_string(chg),
                first_address=first,
                mnemonic_once=str(mnemonic),
            )

    async def restore_wallet(
        self, *, mnemonic_words: str, label: str = "", password: str = ""
    ) -> CreatedWallet:
        """Import from a BIP39 phrase. The phrase is never retained by the provider."""
        async with self._lock:
            try:
                mnemonic = bdk.Mnemonic.from_string(mnemonic_words.strip())
            except Exception as exc:  # bdk Bip39Error family
                raise InvalidMnemonic("not a valid BIP39 mnemonic") from exc
            ext, chg = await asyncio.to_thread(self._descriptors_from_mnemonic, mnemonic, password)
            wallet_id = str(ext.descriptor_id())  # same rule as create_wallet
            if wallet_id in self._wallets:
                # idempotent: restoring a phrase whose wallet is already open
                # returns the existing wallet (no duplicate state, no error);
                # peek (not reveal) so no fresh addresses get burned
                handle = self._wallets[wallet_id]
                return CreatedWallet(
                    wallet_id=wallet_id, network=self.network, label=handle.label,
                    public_descriptor=_public_descriptor_string(ext),
                    change_public_descriptor=_public_descriptor_string(chg),
                    first_address=str(
                        handle.wallet.peek_address(
                            bdk.KeychainKind.EXTERNAL,
                            handle.wallet.derivation_index(bdk.KeychainKind.EXTERNAL) or 0,
                        ).address
                    ),
                    mnemonic_once=None,
                )
            if self._sqlite_path(wallet_id).exists():
                wallet, persister = await asyncio.to_thread(
                    self._load_persisted_wallet, wallet_id, ext, chg
                )
            else:
                wallet, persister = await asyncio.to_thread(
                    self._create_persisted_wallet, wallet_id, ext, chg
                )
            self._wallets[wallet_id] = _WalletHandle(
                wallet_id=wallet_id, network=self.network, label=label,
                descriptor=ext, wallet=wallet, persister=persister,
            )
            first = str(wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address)
            wallet.persist(persister)
            return CreatedWallet(
                wallet_id=wallet_id, network=self.network, label=label,
                public_descriptor=_public_descriptor_string(ext),
                change_public_descriptor=_public_descriptor_string(chg),
                first_address=first,
                mnemonic_once=None,
            )

    async def reopen(
        self,
        wallet_id: str,
        *,
        public_descriptor_external: str,
        public_descriptor_internal: str,
        label: str = "",
    ) -> None:
        """Re-open a previously persisted wallet from PUBLIC descriptors only.

        Used after a process restart: graph/balance/address state returns from
        the on-disk sqlite with zero secret material. Signing still requires a
        fresh unlock (the private wallet is always built from the phrase).
        """
        async with self._lock:
            if wallet_id in self._wallets:
                return  # already open
            if not self._sqlite_path(wallet_id).exists():
                raise WalletNotFound("no persisted state for this wallet id")
            ext = bdk.Descriptor(public_descriptor_external, _bdk_network_kind(self.network))
            chg = bdk.Descriptor(public_descriptor_internal, _bdk_network_kind(self.network))
            wallet, persister = await asyncio.to_thread(
                self._load_persisted_wallet, wallet_id, ext, chg
            )
            self._wallets[wallet_id] = _WalletHandle(
                wallet_id=wallet_id, network=self.network, label=label,
                descriptor=ext, wallet=wallet, persister=persister,
            )

    # -- unlock / lock (in-memory signing vault) ----------------------------------

    async def unlock(
        self, wallet_id: str, *, mnemonic_words: str, ttl_seconds: int | None = None
    ) -> UnlockInfo:
        """Build the in-memory private wallet from the user's phrase.

        The phrase is verified against the wallet's descriptor (a wrong phrase
        is rejected), held ONLY in process memory until the TTL expires, and
        used exclusively by the signing boundary.
        """
        async with self._lock:
            handle = self._handle(wallet_id)
            try:
                mnemonic = bdk.Mnemonic.from_string(mnemonic_words.strip())
            except Exception as exc:
                raise InvalidMnemonic("not a valid BIP39 mnemonic") from exc
            ext, chg = await asyncio.to_thread(self._descriptors_from_mnemonic, mnemonic, "")
            expected_pub = _public_descriptor_string(handle.descriptor)
            actual_pub = _public_descriptor_string(ext)
            if actual_pub != expected_pub:
                raise MnemonicMismatch("recovery phrase does not match this wallet")

            def _build_private() -> bdk.Wallet:
                priv = bdk.Wallet.create_with_params(
                    descriptor=ext, change_descriptor=chg,
                    network=_bdk_network(self.network), persister=bdk.Persister.new_in_memory(),
                    params=bdk.CreateParams(genesis_hash=None, lookahead=25, use_spk_cache=False),
                )
                # cover every derivation index the persisted wallet has revealed so
                # PSBT inputs built by the persisted wallet are signable here
                for kind in (bdk.KeychainKind.EXTERNAL, bdk.KeychainKind.INTERNAL):
                    highest = handle.wallet.derivation_index(kind)
                    for _ in range((highest + 1) if highest is not None else 0):
                        priv.reveal_next_address(kind)
                return priv

            priv = await asyncio.to_thread(_build_private)
            ttl = max(30, ttl_seconds if ttl_seconds is not None else self.unlock_ttl_seconds)
            self._unlocked[wallet_id] = _Unlocked(private_wallet=priv, expires_at=time.monotonic() + ttl)
            return UnlockInfo(wallet_id=wallet_id, expires_at_epoch=time.time() + ttl)

    async def lock(self, wallet_id: str) -> None:
        """Drop the in-memory signing wallet immediately."""
        async with self._lock:
            self._handle(wallet_id)
            self._unlocked.pop(wallet_id, None)

    def _get_unlocked(self, wallet_id: str) -> _Unlocked:
        now = time.monotonic()
        for wid in [w for w, u in self._unlocked.items() if u.expires_at <= now]:
            del self._unlocked[wid]
        unlocked = self._unlocked.get(wallet_id)
        if unlocked is None or unlocked.expires_at <= now:
            raise SigningLocked("signing vault is locked; unlock with the recovery phrase first")
        return unlocked

    # -- protocol surface ----------------------------------------------------------

    async def create_wallet_metadata(self, *, network: Network, label: str) -> dict[str, Any]:
        """Protocol shim: same as create_wallet; mnemonic returned once in the dict."""
        created = await self.create_wallet(label=label)
        return {
            "status": "created",
            "wallet_id": created.wallet_id,
            "network": created.network.value,
            "label": created.label,
            "public_descriptor": created.public_descriptor,
            "change_public_descriptor": created.change_public_descriptor,
            "first_address": created.first_address,
            "mnemonic_once": created.mnemonic_once,
            "mnemonic_display": "one_time — never shown again, never stored",
        }

    async def derive_address(self, wallet_id: str, *, index: int = 0) -> str:
        """Derive the next (or a specific-index) receive address."""
        handle = self._handle(wallet_id)

        def _derive() -> str:
            info = handle.wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL)
            return str(info.address)

        address = await asyncio.to_thread(_derive)
        handle.wallet.persist(handle.persister)
        return address

    async def get_balance_sats(self, wallet_id: str) -> int:
        """Protocol method: total balance (confirmed + unconfirmed)."""
        info = await self.get_balance_info(wallet_id)
        return info.total_sats

    async def get_balance_info(self, wallet_id: str) -> BalanceInfo:
        handle = self._handle(wallet_id)

        def _balance() -> BalanceInfo:
            bal = handle.wallet.balance()
            return BalanceInfo(
                confirmed_sats=bal.confirmed.to_sat(),
                unconfirmed_sats=(bal.trusted_pending.to_sat() + bal.untrusted_pending.to_sat()),
                total_sats=bal.total.to_sat(),
            )

        return await asyncio.to_thread(_balance)

    # -- transaction preparation / signing / broadcast ------------------------------

    async def prepare_transaction(
        self, wallet_id: str, *, destination: str, amount_sats: int, fee_rate_sat_vb: int | None = None
    ) -> PreparedTransaction:
        """Build the unsigned PSBT and the review payload.

        The review payload (destination/amount/fee/network) is exactly what the
        authorization digest binds, so what the user approved is what is signed.
        """
        handle = self._handle(wallet_id)
        if amount_sats <= 0:
            raise InvalidAmount("amount_sats must be positive")
        if amount_sats < _DUST_SATS:
            raise InvalidAmount(f"amount below dust limit ({_DUST_SATS} sats)")

        try:
            dest = bdk.Address(destination, _bdk_network(self.network))
        except Exception as exc:
            # distinguish "valid address for a DIFFERENT network" from garbage
            if _parses_on_other_network(destination, self.network):
                raise NetworkMismatch(
                    f"destination is valid for a different network than {self.network.value}"
                ) from exc
            raise InvalidAddress("destination is not a parseable address") from exc
        if not dest.is_valid_for_network(_bdk_network(self.network)):
            raise NetworkMismatch(
                f"destination is valid for a different network than {self.network.value}"
            )

        warnings: list[str] = ["signing requires an explicit unlocked review confirmation"]
        resolved_fee = fee_rate_sat_vb
        if resolved_fee is None:
            if self.rpc is None:
                resolved_fee = self.fallback_fee_rate_sat_vb
                warnings.append("fee from fallback policy (no chain source configured)")
            else:
                fee, is_fallback = await self.rpc.estimatesmartfee_sat_vb(6)
                resolved_fee = fee if fee > 0 else self.fallback_fee_rate_sat_vb
                if is_fallback:
                    warnings.append("fee from fallback policy (chain estimator has no data)")
        if resolved_fee > self.max_fee_rate_sat_vb:
            warnings.append(
                f"requested fee {resolved_fee} sat/vB exceeds cap; clamped to {self.max_fee_rate_sat_vb}"
            )
            resolved_fee = self.max_fee_rate_sat_vb

        def _build() -> tuple[bdk.Psbt, int]:
            psbt = (
                bdk.TxBuilder()
                .add_recipient(dest.script_pubkey(), bdk.Amount.from_sat(amount_sats))
                .fee_rate(bdk.FeeRate.from_sat_per_vb(int(resolved_fee)))
                .finish(handle.wallet)
            )
            return psbt, psbt.fee() or 0

        try:
            psbt, fee_sats = await asyncio.to_thread(_build)
        except Exception as exc:
            name = type(exc).__name__
            if "InsufficientFunds" in name or "CoinSelection" in name:
                bal = handle.wallet.balance()
                raise InsufficientFunds(
                    f"balance {bal.total.to_sat()} sats cannot cover {amount_sats} sats + fee"
                ) from exc
            raise WalletError(f"transaction construction failed: {name}") from exc

        prepared_id = uuid.uuid4().hex
        prepared = PreparedTransaction(
            wallet_id=wallet_id,
            network=self.network,
            destination=destination,
            amount_sats=amount_sats,
            fee_sats=fee_sats,
            total_sats=amount_sats + fee_sats,
            psbt_or_reference=prepared_id,  # reference only; PSBTs never leave the vault
            warnings=warnings,
        )
        digest = authorization_digest(
            {
                "wallet_id": wallet_id,
                "prepared_id": prepared_id,
                "network": self.network.value,
                "destination": destination,
                "amount_sats": amount_sats,
                "fee_sats": fee_sats,
                "fee_rate_sat_vb": int(resolved_fee),
            }
        )
        self._pending[prepared_id] = _Pending(
            wallet_id=wallet_id, prepared=prepared, digest=digest, psbt=psbt
        )
        return prepared

    def prepared_review(self, prepared_id: str) -> dict[str, Any]:
        """The review payload + digest the API must show before requesting a signature."""
        pending = self._pending.get(prepared_id)
        if pending is None:
            raise PreparedTransactionNotFound(
                f"prepared transaction {prepared_id} not found or already consumed"
            )
        p = pending.prepared
        return {
            "prepared_id": prepared_id,
            "wallet_id": p.wallet_id,
            "network": p.network.value,
            "destination": p.destination,
            "amount_sats": p.amount_sats,
            "fee_sats": p.fee_sats,
            "total_sats": p.total_sats,
            "warnings": list(p.warnings),
            "authorization_digest": pending.digest,
        }

    async def sign_prepared(
        self, prepared_id: str, *, authorization_digest: str, actor: str
    ) -> SignedTransaction:
        """SigningBoundary implementation — the ONLY path from review to signature.

        Validation failures (locked vault, wrong actor, wrong digest) do NOT
        consume the pending transaction; only a completed signature does.
        """
        pending = self._pending.get(prepared_id)
        if pending is None:
            raise PreparedTransactionNotFound(
                f"prepared transaction {prepared_id} not found or already signed"
            )
        if actor.startswith("agent:") or actor in ("dsh", "agent"):
            raise AgentSigningForbidden("agent identities may never sign wallet transactions")
        if authorization_digest != pending.digest:
            raise AuthorizationMismatch(
                "authorization digest does not match the reviewed transaction"
            )
        unlocked = self._get_unlocked(pending.wallet_id)
        # consume only now: every gate passed and a signature will be produced
        del self._pending[prepared_id]

        def _sign() -> SignedTransaction:
            sopts = bdk.SignOptions(
                trust_witness_utxo=True, assume_height=None, allow_all_sighashes=False,
                try_finalize=True, sign_with_tap_internal_key=False, allow_grinding=False,
            )
            ok = unlocked.private_wallet.sign(pending.psbt, sopts)
            if not ok:
                raise WalletError("signing did not reach finalization")
            tx = pending.psbt.extract_tx()
            return SignedTransaction(
                tx_hex=tx.serialize().hex(),
                txid=str(tx.compute_txid()),
                vsize=tx.vsize(),
                fee_sats=pending.psbt.fee() or 0,
            )

        return await asyncio.to_thread(_sign)

    async def broadcast(self, signed_tx: str) -> str:
        """Broadcast a signed raw transaction; uncertain outages are explicit."""
        if self.rpc is None:
            raise BroadcastRejected("no chain source configured; broadcasting is disabled")
        try:
            return await self.rpc.sendrawtransaction(signed_tx)
        except RpcUnavailable as exc:
            raise BroadcastUncertain(
                "node unreachable during broadcast; the transaction outcome is UNKNOWN "
                "and must be resolved by transaction id, not retried blindly"
            ) from exc

    async def probe_mempool(self, tx_hex: str) -> dict | None:
        """Mempool-acceptance dry run (definite reject/accept; no state change)."""
        if self.rpc is None:
            return None
        return await self.rpc.testmempoolaccept(tx_hex)

    async def transaction_status(self, txid: str) -> TxStatus:
        """Best-effort status from the chain source; 'unknown' is honest.

        Tries the raw-transaction query first; without -txindex bitcoind only
        answers it for mempool transactions, so the wallet-scoped
        ``gettransaction`` is tried as a fallback (works when the node's own
        wallet knows the transaction, e.g. our regtest miner wallet).
        """
        if self.rpc is None:
            return TxStatus(txid=txid, state="unknown", confirmations=0, block_height=None)
        raw = None
        try:
            raw = await self.rpc.call("getrawtransaction", txid, 1)
        except RpcError:
            try:
                raw = await self.rpc.call("gettransaction", txid)
            except RpcError:
                raw = None
        if isinstance(raw, dict) and raw.get("confirmations"):
            return TxStatus(
                txid=txid,
                state="confirmed",
                confirmations=int(raw["confirmations"]),
                block_height=raw.get("blockheight"),
            )
        if isinstance(raw, dict) and (raw.get("txid") or raw.get("hex")):
            return TxStatus(txid=txid, state="mempool", confirmations=0, block_height=None)
        return TxStatus(txid=txid, state="unknown", confirmations=0, block_height=None)

    # -- regtest/dev chain-data import (no electrs required on regtest) -------------

    async def import_transaction(self, wallet_id: str, raw_tx_hex: str) -> dict[str, Any]:
        """Feed a chain transaction into the wallet graph (bring-your-own-chain-source).

        On regtest there is no electrum/esplora server; the API layer fetches
        relevant raw transactions via bitcoind RPC and hands them here. This is
        also the documented migration path when a full chain source is attached.
        """
        handle = self._handle(wallet_id)

        def _import() -> dict[str, Any]:
            tx = bdk.Transaction(bytes.fromhex(raw_tx_hex))
            handle.wallet.apply_unconfirmed_txs(
                [bdk.UnconfirmedTx(tx=tx, last_seen=int(time.time()))]
            )
            handle.wallet.persist(handle.persister)
            bal = handle.wallet.balance()
            return {
                "txid": str(tx.compute_txid()),
                "confirmed_sats": bal.confirmed.to_sat(),
                "unconfirmed_sats": (bal.trusted_pending.to_sat() + bal.untrusted_pending.to_sat()),
                "total_sats": bal.total.to_sat(),
            }

        return await asyncio.to_thread(_import)
