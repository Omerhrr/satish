"""Real lnd gRPC adapter (phase 4, decision D11) - lnd v0.21.4-beta.

The node surface is pinned the same way the DSH integration pins its API
(see D8): the gRPC stubs under ``lightning_adapter.lnd_stubs`` are generated
by ``scripts/gen_lnd_stubs.py`` from the release's own ``.proto`` set, so
wire drift is a reviewable diff.

Version-specific API facts captured by the regtest drill
(``scripts/lnd_regtest_drill.py``), recorded here so a re-pin starts honest:
- v0.21.4 removed ``seed_entropy`` from InitWalletRequest;
- the wallet state service enum is ``WalletState`` (was ``WalletStateResponse``);
- the router stub class is ``RouterStub`` (routerrpc).

All grpc/stub imports are lazy: this module imports cleanly on hosts without
grpcio, and only ``mode=lnd`` construction (which requires host/tls/macaroon
anyway) touches them.
"""

from __future__ import annotations

import asyncio
from typing import Any

from wallet_adapter import Network

from lightning_adapter.canned import (
    Invoice as ProviderInvoice,
)
from lightning_adapter.canned import (
    InvoiceNotFound,
    LightningProviderError,
    NodeUnavailable,
    PaymentNotFound,
    PaymentRejected,
    PaymentUncertain,
    PreimageMismatch,
    PreparedPayment,
)
from lightning_adapter.canned import (
    PaymentStatus as ProviderPaymentStatus,
)
from lightning_adapter.state import InvoiceExpired

LND_VERSION = "v0.21.4-beta"


class LndConfigError(LightningProviderError):
    """Provider constructed without the credentials a real node requires."""


class LndLightningProvider:
    """gRPC adapter to a pinned lnd node. Same lifecycle semantics as canned.

    The admin surface (macaroon-gRPC) never leaves this adapter: the agent
    runtime and the Mini App talk to the API layer only.
    """

    implementation = f"lnd {LND_VERSION} (gRPC, stubs generated from the release protos)"

    def __init__(
        self,
        network: Network,
        *,
        rpc_host: str,
        tls_cert_path: str,
        macaroon_path: str,
        max_fee_msat: int,
        base_fee_msat: int = 1_000,
        fee_ppm: int = 1,
        timeout_seconds: float = 15.0,
    ) -> None:
        if network is Network.MAINNET:
            raise ValueError(
                "mainnet is refused at provider construction (release gate D11)"
            )
        if not rpc_host or not tls_cert_path or not macaroon_path:
            raise LndConfigError(
                "lnd mode requires XP_LND_RPC_HOST, XP_LND_TLS_CERT_PATH "
                "and XP_LND_MACAROON_PATH"
            )
        self.network = network
        self.rpc_host = rpc_host
        self.tls_cert_path = tls_cert_path
        self.macaroon_path = macaroon_path
        self.max_fee_msat = max_fee_msat
        self.base_fee_msat = base_fee_msat
        self.fee_ppm = fee_ppm
        self.timeout_seconds = timeout_seconds
        self._stub_lightning: Any = None
        self._stub_router: Any = None
        self._stub_invoices: Any = None
        self._stub_state: Any = None
        self._channel: Any = None

    # channel plumbing

    def _load_stubs(self) -> None:
        """One-time lazy connect: secure credentials from disk, build stubs."""
        if self._stub_lightning is not None:
            return
        try:
            import grpc

            from lightning_adapter.lnd_stubs import (
                invoicesrpc,
                routerrpc,
            )
            from lightning_adapter.lnd_stubs import (
                lightning_pb2_grpc as lgrpc,
            )
            from lightning_adapter.lnd_stubs import (
                stateservice_pb2_grpc as sgrpc,
            )
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise NodeUnavailable(f"lnd stubs/grpc unavailable: {exc}") from exc
        try:
            with open(self.tls_cert_path, "rb") as fh:
                cert = fh.read()
            with open(self.macaroon_path, "rb") as fh:
                macaroon = fh.read().hex()
        except OSError as exc:
            raise NodeUnavailable(f"cannot read lnd credentials: {exc}") from exc
        creds = grpc.composite_channel_credentials(
            grpc.ssl_channel_credentials(cert),
            grpc.metadata_call_credentials(_macaroon_callback(macaroon)),
        )
        channel = grpc.secure_channel(self.rpc_host, creds)
        self._stub_lightning = lgrpc.LightningStub(channel)
        self._stub_router = routerrpc.RouterStub(channel)
        self._stub_invoices = invoicesrpc.InvoicesStub(channel)
        self._stub_state = sgrpc.StateStub(channel)
        self._channel = channel

    async def _call(self, fn, *args, **kwargs) -> Any:
        """Await a gRPC call; outages raise NodeUnavailable (outcome unknown)."""
        self._load_stubs()
        try:
            return await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None, lambda: fn(*args, **kwargs)
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise PaymentUncertain(
                "lnd did not answer within the timeout; outcome unknown"
            ) from exc
        except Exception as exc:  # grpc.RpcError and friends
            if getattr(exc, "code", lambda: None)() is not None:
                code = exc.code()
                # UNAVAILABLE/DEADLINE: node outage -> outcome unknown.
                if code.name in ("UNAVAILABLE", "DEADLINE_EXCEEDED"):
                    raise NodeUnavailable(f"lnd unavailable: {code.name}") from exc
                if code.name == "UNKNOWN" and "unable to route" in str(exc).lower():
                    raise PaymentRejected(str(exc)) from exc
            raise PaymentRejected(str(exc)) from exc

    # receive

    async def create_invoice(
        self, *, amount_msat: int, description: str, expiry_seconds: int
    ) -> ProviderInvoice:
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        if amount_msat <= 0:
            raise ValueError("amount_msat must be positive")
        rsp = await self._call(
            self._stub_lightning.AddInvoice,
            lpb.Invoice(
                value_msat=amount_msat,
                memo=description[:500],
                expiry=expiry_seconds,
            ),
        )
        inv = await self._call(
            self._stub_lightning.LookupInvoice,
            lpb.PaymentHash(r_hash_str=rsp.r_hash, r_hash=rsp.r_hash),
        )
        return ProviderInvoice(
            bolt11=inv.payment_request,
            payment_hash=inv.r_hash.hex(),
            amount_msat=amount_msat,
            description=description,
            expires_at_epoch=inv.expiry + inv.creation_date,
            preimage="",  # the node holds the preimage; it never leaves lnd
        )

    async def invoice_status(self, payment_hash: str) -> tuple[str, ProviderInvoice]:
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        try:
            inv = await self._call(
                self._stub_lightning.LookupInvoice,
                lpb.PaymentHash(r_hash_str=bytes.fromhex(payment_hash),
                                r_hash=bytes.fromhex(payment_hash)),
            )
        except PaymentRejected as exc:
            raise InvoiceNotFound("invoice not found") from exc
        if inv.state == lpb.Invoice.CANCELED:
            return "expired", self._invoice_out(inv)
        if inv.state == lpb.Invoice.SETTLED:
            return "settled", self._invoice_out(inv)
        import time as _t

        if _t.time() >= inv.expiry + inv.creation_date:
            return "expired", self._invoice_out(inv)
        return "pending", self._invoice_out(inv)

    def _invoice_out(self, inv) -> ProviderInvoice:
        return ProviderInvoice(
            bolt11=inv.payment_request,
            payment_hash=inv.r_hash.hex(),
            amount_msat=inv.value_msat,
            description=inv.memo,
            expires_at_epoch=inv.expiry + inv.creation_date,
            preimage="",
        )

    async def settle_invoice(self, payment_hash: str, preimage: str) -> bool:
        """Verify a settlement claim against the node's own invoice state.

        The production caller is the node's SubscribeInvoices stream - the
        preimage must be the node-supplied one; this verification refuses a
        settle if the node has not actually marked the invoice SETTLED.
        """
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        try:
            inv = await self._call(
                self._stub_lightning.LookupInvoice,
                lpb.PaymentHash(r_hash_str=bytes.fromhex(payment_hash),
                                r_hash=bytes.fromhex(payment_hash)),
            )
        except PaymentRejected as exc:
            raise InvoiceNotFound("invoice not found") from exc
        if inv.state == lpb.Invoice.CANCELED:
            raise InvoiceExpired("invoice expired before settlement")
        if inv.state != lpb.Invoice.SETTLED:
            raise PreimageMismatch("node has not settled this invoice")
        if preimage and preimage != inv.r_preimage.hex():
            raise PreimageMismatch("supplied preimage does not match the node's")
        return True

    async def mark_expired(self, payment_hash: str) -> str:
        status, _ = await self.invoice_status(payment_hash)
        return status

    # send

    async def prepare_payment(self, bolt11: str) -> PreparedPayment:
        """Fee preview via the router; clamped to the published cap."""
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        if not bolt11.startswith("ln"):
            raise ValueError("not a bolt11 invoice")
        req = lpb.PayReqString(pay_req=bolt11)
        try:
            decoded = await self._call(self._stub_lightning.DecodePayReq, req)
        except PaymentRejected as exc:
            raise ValueError(f"unparseable bolt11: {exc}") from exc
        amount_msat = decoded.num_msat or decoded.amount * 1000
        # EstimateRouteFee gives the router's view; policy fee on failure.
        try:
            from lightning_adapter.lnd_stubs import routerrpc as rrpc

            fee_rsp = await self._call(
                self._stub_router.EstimateRouteFee,
                rrpc.RouteFeeRequest(dest_bytes_hint=None, amt_sat=amount_msat // 1000),
            )
            estimate = fee_rsp.routing_fee_msat
        except Exception:
            estimate = self.base_fee_msat + (amount_msat * self.fee_ppm) // 1_000_000
        fee_clamped = estimate > self.max_fee_msat
        fee_limit = min(estimate, self.max_fee_msat)
        import secrets as _s

        from wallet_adapter.bdk_provider import authorization_digest

        payment_id = "lp_" + _s.token_hex(12)
        digest = authorization_digest(
            {
                "payment_hash": decoded.payment_hash,
                "amount_msat": amount_msat,
                "fee_limit_msat": fee_limit,
            }
        )
        return PreparedPayment(
            payment_id=payment_id,
            state="prepared",
            amount_msat=amount_msat,
            fee_estimate_msat=estimate,
            fee_limit_msat=fee_limit,
            fee_clamped=fee_clamped,
            authorization_digest=digest,
            description=decoded.description,
        )

    async def submit_payment(
        self,
        *,
        bolt11: str,
        fee_limit_msat: int,
    ) -> ProviderPaymentStatus:
        """SendPaymentV2 with the reviewed cap. Terminal; outages -> uncertain."""
        from lightning_adapter.lnd_stubs import routerrpc as rrpc

        req = rrpc.SendPaymentRequest(
            payment_request=bolt11,
            fee_limit_msat=fee_limit_msat,
            timeout_seconds=30,
            no_inflight_updates=True,
        )
        # SendPaymentV2 streams updates; with no_inflight_updates the stream
        # ends on the terminal state. One awaited pull is enough for the drill
        # path; production wraps this in the service layer's streaming loop.
        call = self._stub_router.SendPaymentV2(request=req)
        try:
            update = next(iter(call))
        except StopIteration as exc:
            raise PaymentUncertain("stream closed without a terminal update") from exc
        except Exception as exc:
            raise self._map_stream_error(exc) from exc
        status = str(update.status).split(".")[-1].lower()
        if "SUCCEEDED" in update.status.name:
            return ProviderPaymentStatus(
                payment_id="",
                payment_hash=update.payment_hash.hex(),
                status="succeeded",
                amount_msat=update.value_msat,
                fee_msat=update.fee_msat,
                preimage=update.payment_preimage.hex() or None,
            )
        if update.failure_reason:
            raise PaymentRejected(f"node rejected: {update.failure_reason}")
        if status not in ("succeeded", "in_flight"):
            raise PaymentRejected(f"unexpected payment state {status}")
        raise PaymentUncertain("payment still in flight at stream end")

    def _map_stream_error(self, exc: Exception) -> Exception:
        code = getattr(exc, "code", lambda: None)()
        if code is not None and code.name in ("UNAVAILABLE", "DEADLINE_EXCEEDED"):
            return NodeUnavailable(f"lnd unavailable: {code.name}")
        text = str(exc).lower()
        if "fee" in text and "limit" in text:
            return PaymentRejected("fee limit exceeded on route")
        if "insufficient" in text or "no route" in text:
            return PaymentRejected("no route within the fee limit")
        return PaymentUncertain("node error with unknown payment outcome")

    async def payment_status(self, payment_hash: str) -> ProviderPaymentStatus:
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        rsp = await self._call(
            self._stub_lightning.ListPayments,
            lpb.ListPaymentsRequest(include_incomplete=True),
        )
        for p in rsp.payments:
            if p.payment_hash.hex() == payment_hash:
                status_map = {"SUCCEEDED": "succeeded", "FAILED": "failed",
                              "IN_FLIGHT": "in_flight"}
                return ProviderPaymentStatus(
                    payment_id=p.payment_request[:16],
                    payment_hash=payment_hash,
                    status=status_map.get(p.status.name, "in_flight"),
                    amount_msat=p.value_msat,
                    fee_msat=p.fee_msat,
                    preimage=p.payment_preimage.hex() or None,
                )
        raise PaymentNotFound("payment not found")

    # node surface

    async def health(self) -> dict:
        from lightning_adapter.lnd_stubs import stateservice_pb2 as spb

        await self._call(self._stub_state.GetState, spb.GetStateRequest())
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        info = await self._call(self._stub_lightning.GetInfo, lpb.GetInfoRequest())
        return {
            "mode": "lnd",
            "network": self.network.value,
            "synced_to_chain": info.synced_to_chain,
            "synced_to_graph": info.synced_to_graph,
            "pubkey": info.identity_pubkey,
            "active_channels": info.num_active_channels,
        }

    async def channels(self) -> list[dict]:
        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        rsp = await self._call(
            self._stub_lightning.ListChannels, lpb.ListChannelsRequest()
        )
        return [
            {
                "channel_id": str(c.chan_id),
                "peer_pubkey": c.remote_pubkey,
                "capacity_msat": c.capacity * 1000,
                "local_msat": c.local_balance * 1000,
                "remote_msat": c.remote_balance * 1000,
                "active": c.active,
            }
            for c in rsp.channels
        ]

    # recovery

    async def export_scb(self) -> tuple[bytes, str]:
        import hashlib

        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        rsp = await self._call(
            self._stub_lightning.ExportChanBackup,
            lpb.ChanBackupExportRequest(),
        )
        blob = rsp.export_chan_backup
        return blob, hashlib.sha256(blob).hexdigest()

    async def restore_scb(self, blob: bytes, checksum: str) -> int:
        import hashlib

        from lightning_adapter.lnd_stubs import lightning_pb2 as lpb

        if hashlib.sha256(blob).hexdigest() != checksum:
            raise LightningProviderError("SCB checksum mismatch - blob corrupted")
        await self._call(
            self._stub_lightning.RestoreChanBackup,
            lpb.RestoreChanBackupRequest(backup=blob),
        )
        return -1  # node reports restored channels via ListChannels


def _macaroon_callback(macaroon_hex: str):
    """lnd expects the macaroon as ``macaroon`` metadata (hex), not bearer auth."""

    def callback(_context, call):
        call([("macaroon", macaroon_hex)], None)

    return callback
