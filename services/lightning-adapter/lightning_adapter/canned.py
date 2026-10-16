"""Canned Lightning provider: lnd-identical semantics, in-memory state.

Purpose (decision D11): make every invoice/payment lifecycle, idempotency
and acceptance criterion testable offline while the real node drill is
blocked by a sandbox defect. This provider is DISCLOSED AS CANNED wherever
it is surfaced (``/lightning/capabilities`` states it verbatim) - it never
pretends a real node exists.

Semantics mirrored from lnd v0.21.4-beta:
- payment_hash = sha256(preimage); settlement requires the preimage;
- expired invoices cannot settle (lnd CANCELED -> our ``expired``);
- payment submission enforces a hard fee limit (SendPaymentV2
  ``fee_limit_msat``); the outcome is terminal;
- SCB export/restore round-trips a checksummed blob (channel.backup shape).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from wallet_adapter import Network
from wallet_adapter.bdk_provider import authorization_digest

from lightning_adapter.state import (
    InvalidTransition,
    InvoiceExpired,
    next_invoice_state,
    next_payment_state,
)

SCB_MAGIC = b"XPSCB1:"


class LightningProviderError(Exception):
    """Base provider error."""


class InvoiceNotFound(LightningProviderError):
    pass


class PaymentNotFound(LightningProviderError):
    pass


class PreimageMismatch(LightningProviderError):
    """Settlement verification failed: preimage does not hash to the hash."""


class PaymentRejected(LightningProviderError):
    """Definite failure - the payment will never succeed."""


class NodeUnavailable(LightningProviderError):
    """Node outage - the outcome of the operation is UNKNOWN."""


class PaymentUncertain(LightningProviderError):
    """Submitted but no terminal outcome observed - do not silently retry."""


class AuthorizationMismatch(LightningProviderError):
    """The presented digest does not bind what the user reviewed."""


@dataclass(frozen=True, slots=True)
class Invoice:
    bolt11: str
    payment_hash: str
    amount_msat: int
    description: str
    expires_at_epoch: int
    preimage: str  # canned seam: the real node holds this server-side


@dataclass(frozen=True, slots=True)
class PreparedPayment:
    payment_id: str
    state: str  # "prepared"
    amount_msat: int
    fee_estimate_msat: int
    fee_limit_msat: int
    fee_clamped: bool
    authorization_digest: str
    description: str


@dataclass(frozen=True, slots=True)
class PaymentStatus:
    payment_id: str
    payment_hash: str
    status: str  # prepared | authorized | in_flight | succeeded | failed
    amount_msat: int
    fee_msat: int = 0
    preimage: str | None = None


@dataclass
class _Channel:
    channel_id: str
    peer_pubkey: str
    capacity_msat: int
    local_msat: int
    remote_msat: int
    active: bool = True


@dataclass
class _InvoiceRecord:
    invoice: Invoice
    status: str = "pending"  # pending | settled | expired
    settled_at_epoch: int | None = None


@dataclass
class _PaymentRecord:
    payment_id: str
    payment_hash: str
    amount_msat: int
    fee_estimate_msat: int
    fee_limit_msat: int
    fee_clamped: bool
    digest: str
    description: str
    status: str = "prepared"
    fee_msat: int = 0
    preimage: str | None = None
    failure_reason: str | None = None


def _canned_bolt11(payment_hash: str, amount_msat: int, expiry: int) -> str:
    """Deterministic canned encoding - NOT a routed invoice.

    Disclosed as canned everywhere; the shape (prefix, amount, hash suffix)
    mirrors what the Mini App parses for display.
    """
    return (
        f"lnbcrt{amount_msat // 1000}n1pj{hashlib.blake2s(  # canned marker
            (payment_hash + str(expiry)).encode(), digest_size=16
        ).hexdigest()}sp5{payment_hash[:52]}"
    )


class CannedLightningProvider:
    """Deterministic lnd-semantics provider for dev/test (disclosed as canned)."""

    implementation = "canned (in-memory lnd-identical semantics; no node attached)"

    def __init__(
        self,
        network: Network = Network.REGTEST,
        *,
        clock: Callable[[], int] | None = None,
        base_fee_msat: int = 1_000,
        fee_ppm: int = 1,
        max_fee_msat: int = 10_000,
        initial_channel: _Channel | None = None,
    ) -> None:
        if network is Network.MAINNET:
            raise ValueError(
                "mainnet is refused at provider construction (release gate D11)"
            )
        self.network = network
        self._clock = clock or (lambda: int(time.time()))
        self.base_fee_msat = base_fee_msat
        self.fee_ppm = fee_ppm
        self.max_fee_msat = max_fee_msat
        self.pubkey = "02canned" + hashlib.sha256(b"canned-node").hexdigest()[:58]
        self._invoices: dict[str, _InvoiceRecord] = {}
        self._payments: dict[str, _PaymentRecord] = {}
        self._channels: list[_Channel] = [
            initial_channel
            or _Channel(
                channel_id="canned:0:0",
                peer_pubkey="02peer" + "0" * 58,
                capacity_msat=10_000_000,
                local_msat=5_000_000,
                remote_msat=5_000_000,
            )
        ]
        self._scb_channels: list[dict] = []

    # receive

    async def create_invoice(
        self, *, amount_msat: int, description: str, expiry_seconds: int
    ) -> Invoice:
        if amount_msat <= 0:
            raise ValueError("amount_msat must be positive")
        if expiry_seconds <= 0:
            raise ValueError("expiry_seconds must be positive")
        preimage = secrets.token_bytes(32).hex()
        payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
        expires_at = self._clock() + expiry_seconds
        invoice = Invoice(
            bolt11=_canned_bolt11(payment_hash, amount_msat, expires_at),
            payment_hash=payment_hash,
            amount_msat=amount_msat,
            description=description,
            expires_at_epoch=expires_at,
            preimage=preimage,
        )
        self._invoices[payment_hash] = _InvoiceRecord(invoice=invoice)
        return invoice

    def _expired(self, record: _InvoiceRecord) -> bool:
        return (
            record.status == "pending"
            and self._clock() >= record.invoice.expires_at_epoch
        )

    async def invoice_status(self, payment_hash: str) -> tuple[str, Invoice]:
        record = self._invoices.get(payment_hash)
        if record is None:
            raise InvoiceNotFound("invoice not found")
        if self._expired(record):
            record.status = "expired"
        return record.status, record.invoice

    async def settle_invoice(self, payment_hash: str, preimage: str) -> bool:
        """Apply a settlement. Returns True for a first settle, False for replay.

        Raises PreimageMismatch when the preimage does not hash to the
        payment_hash (the caller must credit nothing in that case) and
        InvoiceExpired when the invoice elapsed before settlement.
        """
        record = self._invoices.get(payment_hash)
        if record is None:
            raise InvoiceNotFound("invoice not found")
        if self._expired(record):
            record.status = "expired"
        if record.status == "expired":
            raise InvoiceExpired("invoice expired before settlement")
        if not hmac.compare_digest(
            hashlib.sha256(bytes.fromhex(preimage)).hexdigest(), payment_hash
        ):
            raise PreimageMismatch("preimage does not hash to the payment hash")
        if record.status == "settled":
            return False  # idempotent replay: already settled, credit nothing
        record.status = next_invoice_state(record.status, "settled")
        record.settled_at_epoch = self._clock()
        return True

    async def mark_expired(self, payment_hash: str) -> str:
        """Age an invoice out (lnd reports elapsed as CANCELED)."""
        record = self._invoices.get(payment_hash)
        if record is None:
            raise InvoiceNotFound("invoice not found")
        if record.status == "pending":
            if not self._expired(record):
                raise InvalidTransition("invoice has not elapsed yet")
            record.status = next_invoice_state(record.status, "expired")
        return record.status

    # send

    def _estimate_fee_msat(self, amount_msat: int) -> int:
        return self.base_fee_msat + (amount_msat * self.fee_ppm) // 1_000_000

    async def prepare_payment(self, bolt11: str) -> PreparedPayment:
        """Fee preview + authorization digest. Nothing moves."""
        if not bolt11.startswith("ln"):
            raise ValueError("not a bolt11 invoice")
        # The canned invoice encodes the amount and hash; parse from our registry.
        record = next(
            (r for r in self._invoices.values() if r.invoice.bolt11 == bolt11), None
        )
        if record is None:
            raise InvoiceNotFound("unknown bolt11 (canned provider only knows its own)")
        invoice = record.invoice
        if self._expired(record):
            record.status = "expired"
        estimate = self._estimate_fee_msat(invoice.amount_msat)
        fee_clamped = estimate > self.max_fee_msat
        fee_limit = min(estimate, self.max_fee_msat)
        payment_id = "lp_" + secrets.token_hex(12)
        digest = authorization_digest(
            {
                "payment_hash": invoice.payment_hash,
                "amount_msat": invoice.amount_msat,
                "fee_limit_msat": fee_limit,
            }
        )
        record_payment = _PaymentRecord(
            payment_id=payment_id,
            payment_hash=invoice.payment_hash,
            amount_msat=invoice.amount_msat,
            fee_estimate_msat=estimate,
            fee_limit_msat=fee_limit,
            fee_clamped=fee_clamped,
            digest=digest,
            description=invoice.description,
        )
        self._payments[payment_id] = record_payment
        return PreparedPayment(
            payment_id=payment_id,
            state="prepared",
            amount_msat=invoice.amount_msat,
            fee_estimate_msat=estimate,
            fee_limit_msat=fee_limit,
            fee_clamped=fee_clamped,
            authorization_digest=digest,
            description=invoice.description,
        )

    def _record(self, payment_id: str) -> _PaymentRecord:
        rec = self._payments.get(payment_id)
        if rec is None:
            raise PaymentNotFound("payment not found")
        return rec

    async def authorize_payment(self, payment_id: str, digest: str) -> str:
        rec = self._record(payment_id)
        if not hmac.compare_digest(rec.digest, digest):
            raise AuthorizationMismatch("authorization digest does not bind the review")
        rec.status = next_payment_state(rec.status, "authorized")
        return rec.status

    async def submit_payment(self, payment_id: str) -> PaymentStatus:
        """Terminal node submission with the reviewed fee cap enforced."""
        rec = self._record(payment_id)
        if rec.status in ("succeeded", "failed"):
            raise InvalidTransition(f"payment already terminal ({rec.status})")
        invoice_record = self._invoices.get(rec.payment_hash)
        if invoice_record is not None and (
            invoice_record.status == "expired" or self._expired(invoice_record)
        ):
            if invoice_record.status == "pending":
                invoice_record.status = "expired"
            rec.status = next_payment_state(rec.status, "failed")
            rec.failure_reason = "invoice expired before payment"
            raise InvoiceExpired(rec.failure_reason)
        channel = self._channels[0]
        total = rec.amount_msat + rec.fee_limit_msat
        if channel.local_msat < total:
            rec.status = next_payment_state(rec.status, "failed")
            rec.failure_reason = "insufficient outbound liquidity"
            return self._status(rec)  # definite failure, liquidity untouched
        rec.status = next_payment_state(rec.status, "in_flight")
        rec.fee_msat = rec.fee_limit_msat
        channel.local_msat -= rec.amount_msat + rec.fee_msat
        channel.remote_msat += rec.amount_msat + rec.fee_msat
        rec.status = next_payment_state(rec.status, "succeeded")
        rec.preimage = secrets.token_hex(32)
        return self._status(rec)

    async def fail_payment(self, payment_id: str, reason: str) -> PaymentStatus:
        """Explicit failure path (e.g., user cancel / node definite reject)."""
        rec = self._record(payment_id)
        if rec.status == "succeeded":
            raise InvalidTransition("cannot fail a succeeded payment")
        rec.status = next_payment_state(rec.status, "failed")
        rec.failure_reason = reason
        return self._status(rec)

    async def payment_status(self, payment_id: str) -> PaymentStatus:
        return self._status(self._record(payment_id))

    def _status(self, rec: _PaymentRecord) -> PaymentStatus:
        return PaymentStatus(
            payment_id=rec.payment_id,
            payment_hash=rec.payment_hash,
            status=rec.status,
            amount_msat=rec.amount_msat,
            fee_msat=rec.fee_msat,
            preimage=rec.preimage,
        )

    # node surface

    async def health(self) -> dict:
        return {
            "mode": "canned",
            "network": self.network.value,
            "synced_to_chain": True,
            "synced_to_graph": True,
            "pubkey": self.pubkey,
            "active_channels": sum(1 for c in self._channels if c.active),
        }

    async def channels(self) -> list[dict]:
        return [
            {
                "channel_id": c.channel_id,
                "peer_pubkey": c.peer_pubkey,
                "capacity_msat": c.capacity_msat,
                "local_msat": c.local_msat,
                "remote_msat": c.remote_msat,
                "active": c.active,
            }
            for c in self._channels
        ]

    # recovery (SCB)

    async def export_scb(self) -> tuple[bytes, str]:
        """Export a Static Channel Backup blob + its checksum."""
        payload = json.dumps(
            {"version": 1, "channels": self._scb_channels}, sort_keys=True
        ).encode()
        blob = SCB_MAGIC + payload
        return blob, hashlib.sha256(blob).hexdigest()

    async def restore_scb(self, blob: bytes, checksum: str) -> int:
        """Restore from an SCB blob; validates the checksum before applying."""
        if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), checksum):
            raise LightningProviderError("SCB checksum mismatch - blob corrupted")
        if not blob.startswith(SCB_MAGIC):
            raise LightningProviderError("not an XP SCB blob")
        data = json.loads(blob[len(SCB_MAGIC):].decode())
        self._scb_channels = list(data.get("channels", []))
        return len(self._scb_channels)

    def record_channel_for_backup(self, channel_id: str, peer_pubkey: str) -> None:
        """Simulate channel opening so the SCB round-trip has content."""
        self._scb_channels.append({"channel_id": channel_id, "peer_pubkey": peer_pubkey})
