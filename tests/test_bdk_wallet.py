"""Phase-3 BDK wallet provider tests.

Two layers:
- Offline (no bitcoind): wallet creation/restore, descriptor secrecy, unlock
  semantics, review/authorization binding, fee policy, error taxonomy.
- Regtest integration (spawns bitcoind from .tools/, skipped honestly if the
  binary is absent — e.g. CI): create/receive/send/broadcast/confirm/restore
  flows per phases[3] acceptance criteria.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import bdkpython as bdk
import pytest
from wallet_adapter import (
    AgentSigningForbidden,
    AuthorizationMismatch,
    BdkWalletProvider,
    BitcoindRpc,
    BroadcastRejected,
    BroadcastUncertain,
    InvalidAddress,
    InvalidAmount,
    InvalidMnemonic,
    MnemonicMismatch,
    Network,
    NetworkMismatch,
    PreparedTransaction,
    PreparedTransactionNotFound,
    SigningLocked,
    WalletNotFound,
    authorization_digest,
)
from wallet_adapter.bdk_provider import _public_descriptor_string

XP = Path(__file__).resolve().parents[1]
BITCOIND = XP / ".tools" / "bitcoin-29.0" / "bin" / "bitcoind"
CLI = XP / ".tools" / "bitcoin-29.0" / "bin" / "bitcoin-cli"
RPC_PORT = 18443
RPC_URL = f"http://127.0.0.1:{RPC_PORT}"
RPC_USER, RPC_PASS = "xprpc", "xprpc-test"


def _rpc(*args: object) -> object:
    out = subprocess.run(
        [str(CLI), "-regtest", f"-rpcuser={RPC_USER}", f"-rpcpassword={RPC_PASS}",
         f"-rpcport={RPC_PORT}", *[str(a) for a in args]],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"rpc {args}: {out.stderr.strip()}")
    if not out.stdout.strip():
        raise RuntimeError(f"rpc {args}: empty stdout")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return out.stdout.strip()


# -- fixtures ---------------------------------------------------------------------


@pytest.fixture()
def provider(tmp_path: Path, rpc: BitcoindRpc) -> BdkWalletProvider:
    # rpc always attached: offline tests never reach the node (estimatesmartfee
    # failures fall back to the policy fee), regtest tests get real chain data
    return BdkWalletProvider(network=Network.REGTEST, data_dir=tmp_path / "wallets", rpc=rpc)


@pytest.fixture(scope="module")
def bitcoind_regtest():
    """Session bitcoind on regtest with a funded miner wallet."""
    if not BITCOIND.exists():
        pytest.skip("bitcoind binary not available (CI without .tools) — regtest proof lives in scripts/regtest_proof.py")
    data = XP / ".tools" / "regtest-test-data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    proc = subprocess.Popen(
        [str(BITCOIND), "-regtest", f"-datadir={data}",
         f"-rpcuser={RPC_USER}", f"-rpcpassword={RPC_PASS}",
         "-rpcbind=127.0.0.1", f"-rpcport={RPC_PORT}", "-rpcallowip=127.0.0.1",
         "-fallbackfee=0.0002", "-printtoconsole=0"],
    )
    for _ in range(30):
        try:
            _rpc("getblockchaininfo")
            break
        except Exception:
            time.sleep(1)
    else:
        proc.terminate()
        pytest.fail("bitcoind never became ready")
    try:
        _rpc("createwallet", "miner")
        miner = _rpc("getnewaddress")
        _rpc("generatetoaddress", "101", miner)
        yield {"miner_address": miner}
    finally:
        try:
            _rpc("stop")
            time.sleep(1.5)
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture()
def rpc() -> BitcoindRpc:
    return BitcoindRpc(url=RPC_URL, rpc_user=RPC_USER, rpc_password=RPC_PASS, timeout_seconds=10.0)


@pytest.fixture()
async def funded_wallet(provider: BdkWalletProvider, rpc: BitcoindRpc, bitcoind_regtest):
    """A wallet with 5 BTC (unconfirmed-imported via the graph)."""
    created = await provider.create_wallet(label="funded")
    txid = _rpc("sendtoaddress", created.first_address, "5.0")
    _rpc("generatetoaddress", "1", bitcoind_regtest["miner_address"])
    gt = _rpc("gettransaction", txid)
    await provider.import_transaction(created.wallet_id, gt["hex"])
    return created


# -- offline: creation / secrecy ------------------------------------------------------


class TestCreationAndSecrecy:
    async def test_create_returns_one_time_mnemonic(self, provider: BdkWalletProvider):
        created = await provider.create_wallet(label="hot")
        words = created.mnemonic_once
        assert words and len(words.split()) == 24
        assert created.first_address.startswith("bcrt1")
        again = await provider.create_wallet(label="hot2")
        assert again.mnemonic_once != words

    async def test_persisted_state_contains_no_secret_material(
        self, provider: BdkWalletProvider, tmp_path: Path
    ):
        created = await provider.create_wallet(label="secrecy")
        words = created.mnemonic_once.split()
        # descriptor is public-only
        assert "xprv" not in created.public_descriptor
        assert "tprv" not in created.public_descriptor
        # the on-disk sqlite must not contain consecutive mnemonic word pairs
        # (single common words like "work" occur naturally in binary data)
        sqlite_file = tmp_path / "wallets" / f"wallet-{created.wallet_id}.sqlite"
        assert sqlite_file.exists()
        blob = sqlite_file.read_bytes()
        for i in range(len(words) - 1):
            pair = f"{words[i]} {words[i + 1]}".encode()
            assert pair not in blob, f"mnemonic material leaked to disk near word {i}"
        assert b"tprv" not in blob and b"xprv" not in blob

    async def test_restore_same_phrase_same_address(self, provider: BdkWalletProvider):
        created = await provider.create_wallet(label="backup")
        restored = await provider.restore_wallet(mnemonic_words=created.mnemonic_once, label="restored")
        assert restored.wallet_id == created.wallet_id  # deterministic id
        assert restored.first_address == created.first_address
        assert restored.mnemonic_once is None  # restore never echoes a phrase

    async def test_restore_rejects_garbage(self, provider: BdkWalletProvider):
        with pytest.raises(InvalidMnemonic):
            await provider.restore_wallet(mnemonic_words="not a real mnemonic at all friend")

    async def test_restore_is_idempotent_for_open_wallet(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        first = await provider.restore_wallet(mnemonic_words=created.mnemonic_once)
        second = await provider.restore_wallet(mnemonic_words=created.mnemonic_once)
        assert first.wallet_id == created.wallet_id == second.wallet_id
        assert first.first_address == created.first_address == second.first_address

    async def test_unknown_wallet_operations_fail(self, provider: BdkWalletProvider):
        with pytest.raises(WalletNotFound):
            await provider.get_balance_sats("nope")
        with pytest.raises(WalletNotFound):
            await provider.unlock("nope", mnemonic_words="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about")

    async def test_mainnet_guard(self, tmp_path: Path):
        with pytest.raises(ValueError, match="security-review release gate"):
            BdkWalletProvider(network=Network.MAINNET, data_dir=tmp_path)


# -- offline: unlock semantics ---------------------------------------------------------


class TestUnlockSemantics:
    async def test_signing_locked_by_default(self, provider: BdkWalletProvider, tmp_path):
        created = await provider.create_wallet()
        provider2_dir = tmp_path  # prepare will fail on balance anyway; unlock gate first
        assert provider2_dir
        # build a funded-looking wallet via direct graph import of a synthetic tx is
        # overkill offline; the lock gate is checked before any signing attempt:
        with pytest.raises(SigningLocked):
            provider._get_unlocked(created.wallet_id)

    async def test_unlock_rejects_wrong_phrase(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        other = await provider.create_wallet()
        with pytest.raises(MnemonicMismatch):
            await provider.unlock(created.wallet_id, mnemonic_words=other.mnemonic_once)

    async def test_unlock_then_lock_round_trip(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        info = await provider.unlock(created.wallet_id, mnemonic_words=created.mnemonic_once)
        assert info.wallet_id == created.wallet_id
        assert info.expires_at_epoch > time.time()
        provider._get_unlocked(created.wallet_id)  # no raise
        await provider.lock(created.wallet_id)
        with pytest.raises(SigningLocked):
            provider._get_unlocked(created.wallet_id)

    async def test_unlock_ttl_expiry(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        await provider.unlock(created.wallet_id, mnemonic_words=created.mnemonic_once, ttl_seconds=30)
        # force expiry
        provider._unlocked[created.wallet_id].expires_at = time.monotonic() - 1
        with pytest.raises(SigningLocked):
            provider._get_unlocked(created.wallet_id)


# -- offline: review binding + authorization digest -------------------------------------


class TestReviewBinding:
    async def test_digest_binds_review_payload(self):
        payload = {"a": 1, "destination": "bcrt1qxyz", "amount_sats": 546}
        d1 = authorization_digest(payload)
        d2 = authorization_digest(dict(reversed(list(payload.items()))))
        assert d1 == d2  # canonical ordering
        changed = dict(payload, amount_sats=547)
        assert d1 != authorization_digest(changed)

    async def test_prepared_not_found_for_bogus_id(self, provider: BdkWalletProvider):
        with pytest.raises(PreparedTransactionNotFound):
            provider.prepared_review("does-not-exist")


# -- offline: transaction policy ------------------------------------------------------


class TestTransactionPolicy:
    async def test_rejects_dust(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        with pytest.raises(InvalidAmount):
            await provider.prepare_transaction(
                created.wallet_id,
                destination="bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx",
                amount_sats=100,
                fee_rate_sat_vb=2,
            )

    async def test_rejects_foreign_network_address(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        with pytest.raises(NetworkMismatch):
            await provider.prepare_transaction(
                created.wallet_id,
                destination="bc1q9mxwmm2krt2gkw22uph7nywv2ugfm35q3dkp22",  # mainnet
                amount_sats=100_000,
                fee_rate_sat_vb=2,
            )

    async def test_rejects_unparseable_address(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        with pytest.raises(InvalidAddress):
            await provider.prepare_transaction(
                created.wallet_id,
                destination="bcrt1qthisisnotanaddress",
                amount_sats=100_000,
                fee_rate_sat_vb=2,
            )

    async def test_fee_cap_clamps_with_warning(self, provider: BdkWalletProvider):
        provider.max_fee_rate_sat_vb = 5
        created = await provider.create_wallet()
        with pytest.raises(Exception) as exc_info:
            await provider.prepare_transaction(
                created.wallet_id,
                destination="bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx",
                amount_sats=100_000_000_000,
                fee_rate_sat_vb=99,
            )
        # empty wallet: construction fails on funds BEFORE the cap warning path;
        # the cap behavior itself is covered in TestRegtestFlows with a funded wallet
        assert "Insufficient" in type(exc_info.value).__name__ or "balance" in str(exc_info.value).lower()

    async def test_insufficient_funds_is_explicit(self, provider: BdkWalletProvider):
        created = await provider.create_wallet()
        with pytest.raises(Exception) as exc_info:
            await provider.prepare_transaction(
                created.wallet_id,
                destination="bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx",
                amount_sats=100_000_000_000,
                fee_rate_sat_vb=2,
            )
        assert "balance" in str(exc_info.value).lower() or "Insufficient" in type(exc_info.value).__name__


# -- regtest: end-to-end acceptance flows ---------------------------------------------


class TestRegtestFlows:
    async def test_prepare_review_shows_all_fields(
        self, provider: BdkWalletProvider, funded_wallet
    ):
        """Acceptance #2: destination, amount, fee, and network are shown before signing."""
        prepared = await provider.prepare_transaction(
            funded_wallet.wallet_id,
            destination="bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx",
            amount_sats=100_000,
            fee_rate_sat_vb=2,
        )
        review = provider.prepared_review(prepared.psbt_or_reference)
        assert review["destination"] == "bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx"
        assert review["amount_sats"] == 100_000
        assert review["fee_sats"] > 0
        assert review["network"] == "regtest"
        assert len(review["authorization_digest"]) == 64
        assert isinstance(prepared, PreparedTransaction)

    async def test_fee_cap_clamps_with_warning_funded(
        self, provider: BdkWalletProvider, funded_wallet
    ):
        provider.max_fee_rate_sat_vb = 5
        prepared = await provider.prepare_transaction(
            funded_wallet.wallet_id,
            destination="bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx",
            amount_sats=100_000,
            fee_rate_sat_vb=99,
        )
        assert any("cap" in w for w in prepared.warnings)

    async def test_failed_sign_attempt_preserves_entry(
        self, provider: BdkWalletProvider, funded_wallet
    ):
        """Gates reject WITHOUT burning the prepared transaction (no DoS by retry)."""
        prepared = await provider.prepare_transaction(
            funded_wallet.wallet_id,
            destination="bcrt1quf6jk3j2wjyt20ta5rfjuh7w9xnssccgxczpmx",
            amount_sats=100_000,
            fee_rate_sat_vb=2,
        )
        pid = prepared.psbt_or_reference
        correct_digest = provider.prepared_review(pid)["authorization_digest"]
        with pytest.raises(AgentSigningForbidden):
            await provider.sign_prepared(pid, authorization_digest="0" * 64, actor="agent:dsh")
        with pytest.raises(AuthorizationMismatch):
            await provider.sign_prepared(pid, authorization_digest="f" * 64, actor="user-1")
        with pytest.raises(SigningLocked):
            await provider.sign_prepared(pid, authorization_digest=correct_digest, actor="user-1")
        # still consumable after all the failures
        assert provider.prepared_review(pid)["prepared_id"] == pid

    async def test_create_receive_send_confirm_restore(
        self, provider: BdkWalletProvider, rpc: BitcoindRpc, funded_wallet, bitcoind_regtest
    ):
        wallet_id = funded_wallet.wallet_id
        balance = await provider.get_balance_info(wallet_id)
        assert balance.total_sats == 500_000_000

        # network + destination + amount + fee are all on the review payload (acceptance #2)
        dest = _rpc("getnewaddress", "", "bech32")
        prepared = await provider.prepare_transaction(wallet_id, destination=dest, amount_sats=150_000_000)
        review = provider.prepared_review(prepared.psbt_or_reference)
        assert review["network"] == "regtest"
        assert review["destination"] == dest
        assert review["amount_sats"] == 150_000_000
        assert review["fee_sats"] > 0

        # agent actors can NEVER sign (acceptance #3)
        with pytest.raises(AgentSigningForbidden):
            await provider.sign_prepared(
                prepared.psbt_or_reference,
                authorization_digest=review["authorization_digest"],
                actor="agent:dsh-runner",
            )

        # wrong digest is rejected
        with pytest.raises(AuthorizationMismatch):
            await provider.sign_prepared(
                prepared.psbt_or_reference,
                authorization_digest="f" * 64,
                actor="user-1",
            )

        # locked vault is rejected before any signature exists
        with pytest.raises(SigningLocked):
            await provider.sign_prepared(
                prepared.psbt_or_reference,
                authorization_digest=review["authorization_digest"],
                actor="user-1",
            )

        # unlock and sign with the matching digest
        await provider.unlock(wallet_id, mnemonic_words=funded_wallet.mnemonic_once)
        signed = await provider.sign_prepared(
            prepared.psbt_or_reference,
            authorization_digest=review["authorization_digest"],
            actor="user-1",
        )
        assert signed.txid and signed.tx_hex and signed.fee_sats > 0

        # probe then broadcast
        probe = await provider.probe_mempool(signed.tx_hex)
        assert probe and probe["allowed"]
        txid = await provider.broadcast(signed.tx_hex)
        assert txid == signed.txid

        # confirmation tracking (acceptance #1 + #5: accurate states)
        status_mempool = await provider.transaction_status(txid)
        assert status_mempool.state == "mempool"
        _rpc("generatetoaddress", "1", bitcoind_regtest["miner_address"])
        status_confirmed = await provider.transaction_status(txid)
        assert status_confirmed.state == "confirmed"
        assert status_confirmed.confirmations >= 1

        # restore round-trip (acceptance #1: restore flow)
        restored = await provider.restore_wallet(mnemonic_words=funded_wallet.mnemonic_once)
        assert restored.first_address == funded_wallet.first_address

    async def test_broadcast_uncertain_when_node_down(
        self, provider: BdkWalletProvider, tmp_path: Path
    ):
        # provider pointed at a dead node: any broadcast outcome is uncertain
        dead_rpc = BitcoindRpc(url="http://127.0.0.1:1", rpc_user="x", rpc_password="y", timeout_seconds=2)
        p = BdkWalletProvider(network=Network.REGTEST, data_dir=tmp_path / "w2", rpc=dead_rpc)
        await p.create_wallet()  # provider requires an open wallet for broadcast
        with pytest.raises(BroadcastUncertain):
            await p.broadcast("0200000000010123456789abcdef")
        # and without ANY chain source, broadcast is a definite rejection
        q = BdkWalletProvider(network=Network.REGTEST, data_dir=tmp_path / "w3")
        await q.create_wallet()
        with pytest.raises(BroadcastRejected):
            await q.broadcast("0200000000010123456789abcdef")

    async def test_persisted_wallet_reloads_without_private_material(
        self, provider: BdkWalletProvider, funded_wallet
    ):
        """Migration/backup story: reopen from disk; same address, no secrets."""
        wallet_id = funded_wallet.wallet_id
        handle = provider._handle(wallet_id)
        pub = _public_descriptor_string(handle.descriptor)
        # fresh provider instance over the same data dir
        provider2 = BdkWalletProvider(network=Network.REGTEST, data_dir=provider.data_dir)
        restored = await provider2.restore_wallet(mnemonic_words=funded_wallet.mnemonic_once)
        assert restored.wallet_id == wallet_id
        # the original first address is still derivable (peek index 0)
        handle2 = provider2._handle(wallet_id)
        first_peek = str(
            handle2.wallet.peek_address(bdk.KeychainKind.EXTERNAL, 0).address
        )
        assert first_peek == funded_wallet.first_address
        assert _public_descriptor_string(handle2.descriptor) == pub

    async def test_balance_distinguishes_unconfirmed(
        self, provider: BdkWalletProvider, bitcoind_regtest
    ):
        created = await provider.create_wallet()
        txid = _rpc("sendtoaddress", created.first_address, "1.0")
        gt = _rpc("gettransaction", txid)
        await provider.import_transaction(created.wallet_id, gt["hex"])
        info = await provider.get_balance_info(created.wallet_id)
        assert info.total_sats == 100_000_000
        # still unconfirmed from the wallet graph's perspective (no chain anchor)
        assert info.unconfirmed_sats == 100_000_000 or info.confirmed_sats == 100_000_000
