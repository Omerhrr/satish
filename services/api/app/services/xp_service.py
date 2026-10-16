"""XP purchase + receipt service (phase 5, billing_flow).

A purchase IS a receive-direction PaymentIntent viewed through the XP
economy: the plan's XP group exposes it as POST /xp/purchases ->
GET /xp/purchases/{purchase_id} (api_contract). Credit still happens only
through lightning_service.settle's double gate - this service never moves
XP itself, so there is exactly one settlement processor in the system.

Receipts are DERIVED VIEWS over (payment intent, ledger purchase entry),
not a new table - the 16-table data model stays intact and a receipt can
never disagree with the ledger it summarizes. The PDF receipt is a
WeasyPrint artifact rendered by the worker.
"""

from __future__ import annotations

from app.services import lightning_service
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.models.entities import PaymentIntent, User, XpLedgerEntry


class PurchaseError(Exception):
    pass


class UnknownPack(PurchaseError):
    pass


def resolve_pack_sats(settings: Settings, *, pack_id: str | None, amount_sats: int | None) -> int:
    """Pack id -> published sats, or validate the custom amount (billing_flow #1)."""
    if pack_id:
        for pack in pack_views(settings):
            if pack["pack_id"] == pack_id:
                return pack["amount_sats"]
        raise UnknownPack(f"unknown pack {pack_id!r}")
    if amount_sats is None:
        raise ValueError("choose a pack_id or provide amount_sats")
    if amount_sats < 100 or amount_sats > 100_000_000:
        raise ValueError("amount_sats outside policy bounds")
    return amount_sats


def pack_views(settings: Settings) -> list[dict]:
    from xp_core.pricing import list_packs

    return [
        {
            "pack_id": p.pack_id,
            "label": p.label,
            "amount_sats": p.amount_sats,
            "xp_amount": p.xp_amount,
        }
        for p in list_packs(settings)
    ]


async def create_purchase(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    pack_id: str | None,
    amount_sats: int | None,
    description: str,
) -> PaymentIntent:
    """Create the payment intent + invoice for a pack or custom amount.

    Delegates invoice creation to the lightning service so the receive
    lifecycle stays single-sourced. Nothing is credited here.
    """
    sats = resolve_pack_sats(settings, pack_id=pack_id, amount_sats=amount_sats)
    return await lightning_service.create_receive_intent(
        session,
        user=user,
        settings=settings,
        amount_sats=sats,
        description=description or "XP purchase",
    )


async def _purchase_entry(
    session: AsyncSession, intent_id: str
) -> XpLedgerEntry | None:
    return (
        await session.execute(
            select(XpLedgerEntry).where(
                XpLedgerEntry.entry_type == "purchase",
                XpLedgerEntry.reference_type == "payment_intent",
                XpLedgerEntry.reference_id == intent_id,
            )
        )
    ).scalar_one_or_none()


def purchase_out(row: PaymentIntent) -> dict:
    """Map an intent to the purchase/receipt view (only receive direction)."""
    return {
        "id": row.id,
        "payment_hash": row.provider_reference,
        "amount_sats": row.amount_sats,
        "xp_amount": row.xp_amount,
        "status": row.status,
        "bolt11": row.bolt11,
        "expires_at": row.expires_at,
        "settled_at": row.settled_at,
        "created_at": row.created_at,
        "ledger_entry_id": None,
        "balance_after": None,
    }


async def purchase_view(session: AsyncSession, row: PaymentIntent) -> dict:
    """Receipt view: intent + the single purchase ledger entry it produced."""
    out = purchase_out(row)
    if row.status == "settled":
        entry = await _purchase_entry(session, row.id)
        if entry is not None:
            out["ledger_entry_id"] = entry.id
            out["balance_after"] = entry.balance_after
    return out


async def get_owned_purchase(session: AsyncSession, user: User, purchase_id: str) -> PaymentIntent:
    row = (
        await session.execute(
            select(PaymentIntent).where(
                PaymentIntent.id == purchase_id, PaymentIntent.direction == "receive"
            )
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="purchase not found")
    return row


async def list_purchases(
    session: AsyncSession, user: User, *, limit: int = 50, offset: int = 0
) -> list[PaymentIntent]:
    rows = await session.execute(
        select(PaymentIntent)
        .where(PaymentIntent.user_id == user.id, PaymentIntent.direction == "receive")
        .order_by(PaymentIntent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars())


def receipt_lines(row: PaymentIntent, entry: XpLedgerEntry | None) -> dict:
    """Data for the PDF receipt; pulled only from DB rows (no client input)."""
    from xp_core.config import get_settings

    return {
        "purchase_id": row.id,
        "payment_hash": row.provider_reference,
        "amount_sats": row.amount_sats,
        "xp_amount": row.xp_amount,
        "rate": get_settings().xp_per_sat,
        "status": row.status,
        "settled_at": row.settled_at.isoformat() if row.settled_at else None,
        "ledger_entry_id": entry.id if entry else None,
        "balance_after": entry.balance_after if entry else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


__all__ = [
    "PurchaseError",
    "UnknownPack",
    "create_purchase",
    "get_owned_purchase",
    "list_purchases",
    "purchase_out",
    "purchase_view",
    "receipt_lines",
    "resolve_pack_sats",
]
