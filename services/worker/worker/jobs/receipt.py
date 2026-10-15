"""XP purchase receipt PDF (phase 5, deliverable: Receipts and billing UI).

Renders the receipt from DB-owned data only (the purchase intent row and
its ledger purchase entry) — never from client input — so a receipt can
never contradict the ledger. Branded WeasyPrint output, stored as a
private-by-default artifact.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any

from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.db import get_session_factory
from xp_core.logging import get_logger, setup_logging
from xp_core.models.entities import Artifact, PaymentIntent, XpLedgerEntry
from xp_core.services.storage import LocalStorage

log = get_logger(__name__)

_RECEIPT_SHELL = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A5; margin: 1.6cm;
    @bottom-center {{ content: "XP receipt {purchase_id_short} — page " counter(page);
                      font-size: 8px; color: #8a8f98; }} }}
  body {{ font-family: "DejaVu Sans", sans-serif; color: #14181f; line-height: 1.5; }}
  .brand {{ color: #f7931a; font-weight: 700; letter-spacing: 2px; font-size: 11px; }}
  h1 {{ font-size: 20px; margin: 6px 0 2px; }}
  .meta {{ color: #6b7280; font-size: 10px; margin-bottom: 18px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  td {{ padding: 7px 4px; border-bottom: 1px solid #e5e7eb; font-size: 11px; }}
  td.k {{ color: #6b7280; width: 40%; }}
  td.v {{ text-align: right; font-weight: 600; }}
  .total td.v {{ color: #f7931a; font-size: 14px; }}
  .disclaimer {{ margin-top: 24px; padding: 9px 11px; background: #f6f7f9;
                 border-left: 3px solid #f7931a; font-size: 9px; color: #4b5563; }}
</style>
</head>
<body>
  <div class="brand">XP · RECEIPT</div>
  <h1>XP purchase receipt</h1>
  <div class="meta">Purchase {purchase_id} · rendered {rendered_at}</div>
  <table>
    <tr><td class="k">Status</td><td class="v">{status}</td></tr>
    <tr><td class="k">Amount paid</td><td class="v">{amount_sats} sats</td></tr>
    <tr><td class="k">Conversion (published, may change)</td><td class="v">1 sat = {xp_per_sat} XP</td></tr>
    <tr><td class="k">Payment hash</td><td class="v">{payment_hash}</td></tr>
    <tr><td class="k">Ledger entry</td><td class="v">{ledger_entry_id}</td></tr>
    <tr><td class="k">Balance after credit</td><td class="v">{balance_after} XP</td></tr>
    <tr class="total"><td class="k">XP credited</td><td class="v">+{xp_amount} XP</td></tr>
  </table>
  <div class="disclaimer">
    XP is an internal usage credit — it is not Bitcoin, not a blockchain token,
    and not a claim on funds. This receipt summarizes the append-only XP ledger
    entry created when the payment settled; the ledger is the source of truth.
  </div>
</body>
</html>
"""


def _render_html(lines: dict[str, Any]) -> str:
    purchase_id = str(lines.get("purchase_id", ""))
    return _RECEIPT_SHELL.format(
        purchase_id=html.escape(purchase_id),
        purchase_id_short=html.escape(purchase_id[:8]),
        rendered_at=lines.get("rendered_at", ""),
        status=html.escape(str(lines.get("status", ""))),
        amount_sats=lines.get("amount_sats", 0),
        xp_per_sat=lines.get("rate", 0),
        payment_hash=html.escape(str(lines.get("payment_hash") or "-")[:32]),
        ledger_entry_id=html.escape(str(lines.get("ledger_entry_id") or "-")[:13]),
        balance_after=lines.get("balance_after", "-"),
        xp_amount=lines.get("xp_amount", 0),
    )


def _render_and_store(artifact_id: str, lines: dict[str, Any]) -> dict[str, Any]:
    from weasyprint import HTML  # heavy import, lazy

    pdf_bytes = HTML(string=_render_html(lines)).write_pdf()
    storage = LocalStorage(get_settings().artifact_dir)
    key = f"receipts/{lines.get('purchase_id', artifact_id)}/receipt.pdf"
    stored = storage.save_bytes(key, pdf_bytes)
    return {"object_key": key, "size_bytes": stored.size_bytes, "sha256": stored.sha256}


async def generate_receipt_pdf(
    ctx: dict[str, Any],
    *,
    artifact_id: str,
    purchase_id: str,
) -> dict[str, Any]:
    """Arq job (also inline via the dev bridge). Reads its own DB rows."""
    setup_logging(get_settings().log_level)
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(PaymentIntent).where(
                    PaymentIntent.id == purchase_id, PaymentIntent.direction == "receive"
                )
            )
        ).scalar_one_or_none()
        entry = (
            await session.execute(
                select(XpLedgerEntry).where(
                    XpLedgerEntry.entry_type == "purchase",
                    XpLedgerEntry.reference_type == "payment_intent",
                    XpLedgerEntry.reference_id == purchase_id,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"purchase {purchase_id} not found")

    from datetime import UTC, datetime

    lines = {
        "purchase_id": row.id,
        "payment_hash": row.provider_reference,
        "amount_sats": row.amount_sats,
        "xp_amount": row.xp_amount,
        "rate": get_settings().xp_per_sat,
        "status": row.status,
        "settled_at": row.settled_at,
        "ledger_entry_id": entry.id if entry else None,
        "balance_after": entry.balance_after if entry else None,
        "rendered_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    stored = await asyncio.to_thread(_render_and_store, artifact_id, lines)

    async with factory() as session:
        art = (
            await session.execute(select(Artifact).where(Artifact.id == artifact_id))
        ).scalar_one_or_none()
        if art is not None:
            art.object_key = stored["object_key"]
            art.size_bytes = stored["size_bytes"]
            art.sha256 = stored["sha256"]
            art.status = "ready"
            await session.commit()
    log.info("receipt_pdf_ready", purchase_id=purchase_id, artifact_id=artifact_id)
    return stored
