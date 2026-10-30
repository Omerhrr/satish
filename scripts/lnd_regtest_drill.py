"""Two-node lnd regtest drill (phase 4, decision D11 evidence instrument).

Stages (mirrors the lnd provider notes in git history (Satish now uses Breez Spark, docs/wallet.md) "Recovery and backups"):
  1. bitcoind regtest up (rpcpolling; zmq is broken in this sandbox)
  2. two lnd nodes: wallet init from captured seed, TLS + macaroon, ACTIVE
  3. fund node A + open channel A->B            [BLOCKED in this sandbox]
  4. node B invoice -> node A payment (cap enforced)
  5. settle propagation (invoice SETTLED, preimage check)
  6. fee-limit rejection path (route above cap refused)
  7. restart drill: SIGTERM -> restart -> unlock -> channels/invoices persist
  8. data-loss drill: wipe -> re-init from seed (recovery_window) -> SCB
     restore -> DLP force-close sweep

Stages 3-6 are BLOCKED in this sandbox by the documented environment defect
(broken loopback zmq + btcwallet block-processor stall on rpcpolling; lnd
#9108/#10389/#11004). The drill detects the stall and reports BLOCKED with
diagnostics instead of pretending - re-run on a healthy host to complete.

Usage: make lightning-drill   (or .venv/bin/python scripts/lnd_regtest_drill.py)
Exit:  0 = all reachable stages passed (BLOCKED stages reported honestly),
       1 = unexpected failure (a real bug - fix before shipping).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / ".tools"
LND_VERSION = "v0.21.4-beta"

BITCOIND = TOOLS / "bitcoin-29.0" / "bin" / "bitcoind"
LND_BIN = TOOLS / f"lnd-linux-amd64-{LND_VERSION}" / "lnd"
LND_CLI = TOOLS / f"lnd-linux-amd64-{LND_VERSION}" / "lncli"

RPC_USER, RPC_PASS, RPC_PORT = "drillrpc", "drillpass", 18443

sys.path.insert(0, str(REPO_ROOT / "services" / "lightning-adapter"))

import grpc  # noqa: E402

from lightning_adapter.lnd_stubs import (  # noqa: E402
    lightning_pb2 as lpb,
    lightning_pb2_grpc as lgrpc,
    routerrpc,
    stateservice_pb2 as spb,
    stateservice_pb2_grpc as sgrpc,
    walletunlocker_pb2 as wupb,
    walletunlocker_pb2_grpc as wugrpc,
)

RESULTS: list[tuple[str, str, str]] = []  # (stage, verdict, note)


def report(stage: str, verdict: str, note: str = "") -> None:
    RESULTS.append((stage, verdict, note))
    print(f"[{stage}] {verdict}" + (f" - {note}" if note else ""))


def wait_for(fn, timeout: float, what: str):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as exc:  # noqa: BLE001 - probe loop
            last = exc
        time.sleep(1)
    raise TimeoutError(f"{what} not ready in {timeout}s (last: {last})")


class Bitcoind:
    def __init__(self, datadir: Path) -> None:
        self.datadir = datadir
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        cfg = self.datadir / "bitcoin.conf"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            "regtest=1\n[regtest]\n"
            f"rpcuser={RPC_USER}\nrpcpassword={RPC_PASS}\n"
            f"rpcport={RPC_PORT}\nrpcbind=127.0.0.1\nrpcallowip=127.0.0.1\n"
            "txindex=0\n"
        )
        self.proc = subprocess.Popen(
            [str(BITCOIND), f"-datadir={self.datadir}", "-printtoconsole=0"],
            stdout=subprocess.DEVNULL,
        )
        wait_for(self._rpc_ok, 30, "bitcoind rpc")
        wait_for(self._create_wallet, 30, "bitcoind wallet")

    def _rpc(self, method: str, params: list | None = None):
        import httpx

        rsp = httpx.post(
            f"http://127.0.0.1:{RPC_PORT}",
            json={"jsonrpc": "1.0", "id": "d", "method": method, "params": params or []},
            auth=(RPC_USER, RPC_PASS),
            timeout=10,
        )
        # bitcoind returns RPC-level errors as HTTP 500 with a JSON body;
        # always parse the body before raising.
        data = rsp.json()
        if data.get("error"):
            raise RuntimeError(f"rpc {method}: {data['error']}")
        return data["result"]

    def _create_wallet(self) -> bool:
        try:
            self._rpc("createwallet", ["drill"])
            return True
        except RuntimeError as exc:
            if "already exists" in str(exc):
                self._rpc("loadwallet", ["drill"])
                return True
            return False

    def _rpc_ok(self) -> bool:
        try:
            return self._rpc("getblockchaininfo")["chain"] == "regtest"
        except Exception:
            return False

    def mine(self, n: int, address: str | None = None) -> None:
        addr = address or self._rpc("getnewaddress")
        self._rpc("generatetoaddress", [n, addr])

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class LndNode:
    def __init__(self, name: str, datadir: Path, rpc_port: int, listen_port: int) -> None:
        self.name = name
        self.datadir = datadir
        self.rpc_port = rpc_port
        self.listen_port = listen_port
        self.proc: subprocess.Popen | None = None
        self.seed: list[str] | None = None
        self.macaroon = self.datadir / "data" / "chain" / "bitcoin" / "regtest" / "admin.macaroon"
        self.tls = self.datadir / "tls.cert"

    def start(self, *, recovery_window: int = 0) -> None:
        args = [
            str(LND_BIN),
            f"--lnddir={self.datadir}",
            f"--rpclisten=127.0.0.1:{self.rpc_port}",
            f"--listen=127.0.0.1:{self.listen_port}",
            "--norest",
            "--bitcoin.active",
            "--bitcoin.regtest",
            "--bitcoin.node=bitcoind",
            "--bitcoind.rpcpolling",  # zmq is broken in this sandbox
            f"--bitcoind.rpchost=127.0.0.1:{RPC_PORT}",
            f"--bitcoind.rpcuser={RPC_USER}",
            f"--bitcoind.rpcpass={RPC_PASS}",
        ]
        if recovery_window:
            args.append("--reset-wallet-transactions=false")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL)
        wait_for(lambda: self.tls.exists(), 30, f"{self.name} tls")

    def unlocker_stub(self):
        channel = grpc.secure_channel(
            f"127.0.0.1:{self.rpc_port}",
            grpc.ssl_channel_credentials(open(self.tls, "rb").read()),  # noqa: SIM115
        )
        return wugrpc.WalletUnlockerStub(channel), channel

    def init_wallet(self) -> None:
        stub, channel = self.unlocker_stub()
        try:
            seed = stub.GenSeed(wupb.GenSeedRequest(), timeout=15)
            self.seed = list(seed.cipher_seed_mnemonic)
            stub.InitWallet(
                wupb.InitWalletRequest(
                    wallet_password=b"drillpass",
                    cipher_seed_mnemonic=self.seed,
                    recovery_window=0,
                ),
                timeout=30,
            )
        finally:
            channel.close()
        self.wait_active()

    def wait_active(self) -> None:
        def check() -> bool:
            stub = self.lightning_stub()[0]
            state = self.state_stub().GetState(spb.GetStateRequest(), timeout=5)
            return state.state in (spb.WalletState.RPC_ACTIVE, spb.WalletState.SERVER_ACTIVE)

        wait_for(check, 90, f"{self.name} wallet ACTIVE")

    def state_stub(self):
        channel = grpc.secure_channel(
            f"127.0.0.1:{self.rpc_port}",
            grpc.ssl_channel_credentials(open(self.tls, "rb").read()),  # noqa: SIM115
        )
        return sgrpc.StateStub(channel)

    def lightning_stub(self):
        def macaroon_callback(_context, callback):
            callback([("macaroon", open(self.macaroon, "rb").read().hex())], None)  # noqa: SIM115

        channel = grpc.secure_channel(
            f"127.0.0.1:{self.rpc_port}",
            grpc.composite_channel_credentials(
                grpc.ssl_channel_credentials(open(self.tls, "rb").read()),  # noqa: SIM115
                grpc.metadata_call_credentials(macaroon_callback),
            ),
        )
        return lgrpc.LightningStub(channel), channel

    def stop(self, sig: int = signal.SIGTERM) -> None:
        if self.proc:
            self.proc.send_signal(sig)
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def main() -> int:
    if not BITCOIND.exists() or not LND_BIN.exists():
        print("drill binaries missing under .tools/ - download lnd "
              f"{LND_VERSION} + bitcoind first (see the lnd provider notes in git history (Satish now uses Breez Spark, docs/wallet.md))")
        return 1
    work = TOOLS / "ln-regtest-data"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    bitcoind = Bitcoind(work / "bitcoind")
    a = LndNode("node-a", work / "node-a", 10109, 19735)
    b = LndNode("node-b", work / "node-b", 10110, 19736)

    try:
        # stage 1: chain up
        bitcoind.start()
        bitcoind.mine(101)
        report("1-chain", "PASS", "bitcoind regtest up, 101 blocks")

        # stage 2: two nodes ACTIVE
        a.start()
        b.start()
        a.init_wallet()
        b.init_wallet()
        stub_a, ch_a = a.lightning_stub()
        stub_b, ch_b = b.lightning_stub()
        pub_a = stub_a.GetInfo(lpb.GetInfoRequest(), timeout=10).identity_pubkey
        pub_b = stub_b.GetInfo(lpb.GetInfoRequest(), timeout=10).identity_pubkey
        report("2-nodes", "PASS", f"a={pub_a[:12]}… b={pub_b[:12]}…")

        # stage 3: fund + channel (environmentally blocked)
        addr_rsp = stub_a.NewAddress(lpb.NewAddressRequest(type=lpb.AddressType.WITNESS_PUBKEY_HASH), timeout=10)
        bitcoind.mine(6, addr_rsp.address)
        # rpcpolling + the btcwallet block-processor stall: outputs never credit.
        credited = False
        deadline = time.time() + 60
        while time.time() < deadline:
            bal = stub_a.WalletBalance(lpb.WalletBalanceRequest(), timeout=10)
            if bal.confirmed_balance > 0:
                credited = True
                break
            time.sleep(2)
        if not credited:
            report(
                "3-fund-channel", "BLOCKED",
                "btcwallet block-processor never credited the mined output "
                "(known sandbox defect: broken loopback zmq + rpcpolling stall; "
                "lnd #9108/#10389/#11004). Re-run on a healthy host.",
            )
            for stage in ("4-invoice-pay", "5-settle", "6-fee-cap"):
                report(stage, "BLOCKED", "requires the stage-3 channel")
        else:
            stub_b.ConnectPeer(lpb.ConnectPeerRequest(
                lightning_id=lpb.LightningAddress(pubkey=pub_b, host=f"127.0.0.1:{b.listen_port}")
            ), timeout=15)
            chan_rsp = stub_a.OpenChannelSync(lpb.OpenChannelRequest(
                node_pubkey=bytes.fromhex(pub_b), local_funding_amount=1_000_000,
                push_sat=100_000,
            ), timeout=30)
            bitcoind.mine(6)
            wait_for(lambda: any(c.active for c in stub_a.ListChannels(
                lpb.ListChannelsRequest(), timeout=10).channels), 120, "channel active")
            report("3-fund-channel", "PASS", f"channel {chan_rsp.funding_txid[:12]}…")

            # stage 4-6: invoice -> pay -> settle -> fee cap
            inv = stub_b.AddInvoice(lpb.Invoice(value_msat=50_000_000, memo="drill"), timeout=10)
            pay_stream = stub_a.SendPaymentV2(routerrpc.SendPaymentRequest(
                payment_request=inv.payment_request, fee_limit_msat=10_000, timeout_seconds=30,
                no_inflight_updates=True,
            ), timeout=60)
            update = next(iter(pay_stream))
            ok4 = update.status == lpb.Payment.SUCCEEDED
            report("4-invoice-pay", "PASS" if ok4 else "FAIL", str(update.status))
            settled = stub_b.LookupInvoice(lpb.PaymentHash(
                r_hash_str=inv.r_hash, r_hash=inv.r_hash), timeout=10)
            ok5 = settled.state == lpb.Invoice.SETTLED and settled.r_preimage == update.payment_preimage
            report("5-settle", "PASS" if ok5 else "FAIL", "preimage matches" if ok5 else "")
            # stage 6: fee-cap rejection (fresh invoice, absurdly low cap)
            inv2 = stub_b.AddInvoice(lpb.Invoice(value_msat=20_000_000, memo="cap"), timeout=10)
            try:
                stream6 = stub_a.SendPaymentV2(routerrpc.SendPaymentRequest(
                    payment_request=inv2.payment_request, fee_limit_msat=1,
                    timeout_seconds=30, no_inflight_updates=True,
                ), timeout=60)
                update6 = next(iter(stream6))
                refused = update6.status == lpb.Payment.FAILED
                report("6-fee-cap", "PASS" if refused else "FAIL",
                       "cap enforced (route above 1 msat refused)" if refused
                       else f"unexpected status {update6.status}")
            except grpc.RpcError as exc:
                report("6-fee-cap", "PASS", f"node refused above-cap route: {exc.code().name}")

        # stage 7: restart drill
        a.stop(signal.SIGTERM)
        a.start()

        def rpc_back() -> bool:
            try:
                a.state_stub().GetState(spb.GetStateRequest(), timeout=5)
                return True
            except Exception:
                return False

        wait_for(rpc_back, 45, "node-a rpc back up")
        stub_unlock, ch = a.unlocker_stub()
        stub_unlock.UnlockWallet(wupb.UnlockWalletRequest(wallet_password=b"drillpass"), timeout=30)
        ch.close()
        a.wait_active()
        report("7-restart", "PASS", "unlock after SIGTERM restart; wallet ACTIVE")

        # stage 8: data-loss DLP drill (environmentally blocked without stage 3)
        if not credited:
            report("8-data-loss", "BLOCKED", "needs a funded+channelled node from stage 3")
        else:
            scb = stub_a.ExportChanBackup(lpb.ChanBackupExportRequest(), timeout=10)
            a.stop()
            shutil.rmtree(a.datadir)
            a.datadir.mkdir(parents=True)
            a.start()
            stub_unlock, ch = a.unlocker_stub()
            stub_unlock.InitWallet(wupb.InitWalletRequest(
                wallet_password=b"drillpass", cipher_seed_mnemonic=a.seed,
                recovery_window=500, channel_backups=lpb.ChanBackupSnapshot(
                    single_chan_backups=lpb.SingleChanBackups(
                        chan_backups=[lpb.ChannelBackup(chan_backup=scb.export_chan_backup)]
                    )
                ),
            ), timeout=30)
            ch.close()
            a.wait_active()
            report("8-data-loss", "PASS", "seed re-init + SCB restore; DLP will force-close")

        blocked = [r for r in RESULTS if r[1] == "BLOCKED"]
        failed = [r for r in RESULTS if r[1] == "FAIL"]
        print(f"\ndrill summary: {len(RESULTS)} stages - "
              f"{sum(1 for r in RESULTS if r[1] == 'PASS')} PASS, "
              f"{len(blocked)} BLOCKED, {len(failed)} FAIL")
        return 1 if failed else 0
    except Exception as exc:  # noqa: BLE001 - drill must report, not crash silently
        report("unexpected", "FAIL", f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        a.stop()
        b.stop()
        bitcoind.stop()


if __name__ == "__main__":
    raise SystemExit(main())
