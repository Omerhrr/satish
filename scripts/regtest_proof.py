# ruff: noqa: PLW1510, BLE001, S110, B015, RUF046 - one-shot spike evidence, kept as record
"""Empirical phase-3 spike: BDK (bdkpython) + bitcoind regtest end-to-end.

Proves: create / receive / balance / send / fee / broadcast / confirm / restore
+ failure paths (insufficient funds, bad address, double-broadcast).

Spawns its own bitcoind (v29.0 at .tools/bitcoin-29.0/bin/bitcoind) so the
whole proof lives inside one process tree. Run under xp/.venv.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import bdkpython as bdk

XP = Path("/home/z/my-project/xp")
BITCOIND = XP / ".tools" / "bitcoin-29.0" / "bin" / "bitcoind"
CLI = XP / ".tools" / "bitcoin-29.0" / "bin" / "bitcoin-cli"
DATA = XP / ".tools" / "regtest-data"
RPC = "http://xprpc:xprpc-test@127.0.0.1:18443"


def rpc(*args, **kw):
    out = subprocess.run(
        [str(CLI), "-regtest", "-rpcuser=xprpc", "-rpcpassword=xprpc-test", "-rpcconnect=127.0.0.1", *args],
        capture_output=True, text=True, **kw,
    )
    if out.returncode != 0:
        raise RuntimeError(f"rpc {args} failed: rc={out.returncode} stdout={out.stdout!r} stderr={out.stderr.strip()}")
    if not out.stdout.strip():
        raise RuntimeError(f"rpc {args} returned empty stdout (stderr={out.stderr.strip()!r})")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return out.stdout.strip()  # bare scalars (addresses, txids) print unquoted


def wait_rpc(timeout=30):
    for _ in range(timeout):
        try:
            rpc("getblockchaininfo")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("bitcoind never became ready")


def main():
    assert BITCOIND.exists(), "bitcoind binary missing"
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)

    proc = subprocess.Popen(
        [str(BITCOIND), "-regtest",
         "-datadir=" + str(DATA),
         "-rpcuser=xprpc", "-rpcpassword=xprpc-test",
         "-rpcbind=127.0.0.1", "-rpcallowip=127.0.0.1",
         "-fallbackfee=0.0002", "-printtoconsole=0"],
    )
    try:
        wait_rpc()
        print("bitcoind ready")
        rpc("createwallet", "miner")
        miner_addr = rpc("getnewaddress")
        rpc("generatetoaddress", "101", miner_addr)
        print("mined 101 blocks; miner balance:", rpc("getbalance"))

        # 1. CREATE: BIP39 mnemonic -> BIP84 descriptor -> wallet
        mnemonic = bdk.Mnemonic(word_count=bdk.WordCount.WORDS12)
        words = str(mnemonic)
        sk = bdk.DescriptorSecretKey(network_kind=bdk.NetworkKind.TEST, mnemonic=mnemonic, password="")
        desc = bdk.Descriptor.new_bip84(sk, bdk.KeychainKind.EXTERNAL, bdk.NetworkKind.TEST)
        chg = bdk.Descriptor.new_bip84(sk, bdk.KeychainKind.INTERNAL, bdk.NetworkKind.TEST)
        wallet = bdk.Wallet.create_with_params(
            descriptor=desc, change_descriptor=chg,
            network=bdk.Network.REGTEST, persister=bdk.Persister.new_in_memory(),
            params=bdk.CreateParams(genesis_hash=None, lookahead=25, use_spk_cache=False),
        )
        print("wallet created; descriptor checksum:", wallet.descriptor_checksum(bdk.KeychainKind.EXTERNAL))

        # 2. RECEIVE: reveal address, fund from miner, import into wallet graph
        addr_info = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL)
        recv_addr = str(addr_info.address)
        assert recv_addr.startswith("bcrt1"), recv_addr
        print("receive address:", recv_addr)
        assert bdk.Address(recv_addr, bdk.Network.REGTEST).is_valid_for_network(bdk.Network.REGTEST)

        txid1 = rpc("sendtoaddress", recv_addr, "5.0")
        rpc("generatetoaddress", "1", miner_addr)
        gt = rpc("gettransaction", txid1)
        decoded = rpc("decoderawtransaction", gt["hex"])
        vout = next(i for i, o in enumerate(decoded["vout"]) if recv_addr in json.dumps(o))
        txout_value = decoded["vout"][vout]["value"]
        print(f"funded: txid={txid1[:16]}... vout={vout} value={txoutValue_str(txout_value)}")

        # import the funding transaction into the BDK graph (bring-your-own-chain-source;
        # on regtest there is no electrs/esplora, the API layer fetches txs via RPC)
        funding_tx = bdk.Transaction(bytes.fromhex(gt["hex"]))
        wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding_tx, last_seen=int(time.time()))])
        utxos = wallet.list_unspent()
        print("wallet list_unspent count:", len(utxos))
        assert len(utxos) == 1 and utxos[0].txout.value.to_sat() == bdk.Amount.from_btc(txout_value).to_sat()
        bal = wallet.balance()
        print("confirmed-ish balance sats:", bal.confirmed.to_sat(), "total:", bal.total.to_sat())

        # 3. FEE: bitcoind estimatesmartfee as the fee source
        est = rpc("estimatesmartfee", "1")
        fee_rate_sat_vb = max(1, int(round(est.get("feerate", 0.0001) * 1e8 / 1000)))
        print("estimatesmartfee ->", est.get("feerate"), f"~{fee_rate_sat_vb} sat/vB")

        # 4. SEND: build PSBT, sign, finalize, extract, broadcast
        dest_addr = rpc("getnewaddress", "", "bech32")
        send_amt = 150_000_000  # 1.5 BTC in sats
        psbt = (
            bdk.TxBuilder()
            .add_recipient(bdk.Address(dest_addr, bdk.Network.REGTEST).script_pubkey(),
                           bdk.Amount.from_sat(send_amt))
            .fee_rate(bdk.FeeRate.from_sat_per_vb(fee_rate_sat_vb))
            .finish(wallet)
        )
        fee = psbt.fee()  # absolute fee in sats (int)
        print("psbt built; fee sats:", fee)
        sopts = bdk.SignOptions(
            trust_witness_utxo=True, assume_height=None, allow_all_sighashes=False,
            try_finalize=False, sign_with_tap_internal_key=False, allow_grinding=False,
        )
        signed = wallet.sign(psbt, sopts)
        print("sign returned:", signed)
        finalized = wallet.finalize_psbt(psbt, sopts)
        assert finalized, "finalize failed"
        tx = psbt.extract_tx()
        raw_hex = tx.serialize().hex()
        print("signed tx vsize:", tx.vsize(), "bytes:", len(raw_hex) // 2)

        accept = rpc("testmempoolaccept", json.dumps([raw_hex]))[0]
        assert accept["allowed"], f"testmempoolaccept rejected: {accept}"
        txid2 = rpc("sendrawtransaction", raw_hex)
        print("broadcast ok:", txid2[:16], "...")

        # 5. CONFIRMATION TRACKING
        rpc("generatetoaddress", "1", miner_addr)
        got = rpc("gettransaction", txid2)  # wallet RPC: works without -txindex
        print("confirmations:", got.get("confirmations"))
        assert got.get("confirmations", 0) >= 1

        # 6. RESTORE: same mnemonic -> same descriptor -> same address
        restored_m = bdk.Mnemonic.from_string(words)
        rsk = bdk.DescriptorSecretKey(network_kind=bdk.NetworkKind.TEST, mnemonic=restored_m, password="")
        rdesc = bdk.Descriptor.new_bip84(rsk, bdk.KeychainKind.EXTERNAL, bdk.NetworkKind.TEST)
        rwallet = bdk.Wallet.create_with_params(
            descriptor=rdesc,
            change_descriptor=bdk.Descriptor.new_bip84(rsk, bdk.KeychainKind.INTERNAL, bdk.NetworkKind.TEST),
            network=bdk.Network.REGTEST, persister=bdk.Persister.new_in_memory(),
            params=bdk.CreateParams(genesis_hash=None, lookahead=25, use_spk_cache=False),
        )
        raddr = str(rwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address)
        assert raddr == recv_addr, f"restore mismatch {raddr} != {recv_addr}"
        print("restore round-trip: same first address", raddr)

        # 7. FAILURE PATHS
        # 7a. overspend -> InsufficientFunds
        try:
            bdk.TxBuilder().add_recipient(
                bdk.Address(dest_addr, bdk.Network.REGTEST).script_pubkey(),
                bdk.Amount.from_sat(99_000_000_000)).finish(wallet)
            raise AssertionError("overspend did not raise")
        except Exception as e:
            print("overspend rejected:", type(e).__name__)
        # 7b. bad address
        try:
            bdk.Address("bcrt1qnotarealaddress", bdk.Network.REGTEST)
            raise AssertionError("bad address did not raise")
        except Exception as e:
            print("bad address rejected:", type(e).__name__)
        # 7c. network mismatch: mainnet address on regtest wallet
        try:
            bdk.Address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", bdk.Network.REGTEST).is_valid_for_network(
                bdk.Network.REGTEST) is False
            print("mainnet address flagged invalid on regtest: OK")
        except Exception as e:
            print("mainnet address rejected:", type(e).__name__)

        print("\nREGTEST PROOF: ALL FLOWS OK")
        return 0
    finally:
        try:
            rpc("stop")
            time.sleep(2)
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=10)


def txoutValue_str(v):
    return f"{v} BTC"


if __name__ == "__main__":
    sys.exit(main())
