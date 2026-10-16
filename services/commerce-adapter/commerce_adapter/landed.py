"""Landed-cost estimate template (phase-8 deliverable #6, acceptance #2).

A deterministic, line-typed template: every line carries a VALUE, a KIND
(estimate | observed | assumption) and a BASIS (where the number came from):

- asking price          -> estimate (listing/auction/supplier snapshot),
                           optionally bound to a cited source fact
- official duty/levy    -> observed (official published rate), only when the
                           caller binds an official source
- shipping/insurance/fees -> assumption (user-supplied), unless bound to a
                           cited source fact
- verified cost         -> none exist in this pipeline, and the output says
                           so explicitly (nothing here is a paid invoice)

The total is arithmetic over the lines; it is labeled an ESTIMATE in the
output itself. Nothing is invented: unparseable or missing inputs are
refused, not guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


class LandedCostError(ValueError):
    pass


@dataclass
class CostLine:
    key: str
    label: str
    value: float
    kind: str  # estimate | observed | assumption
    basis: str  # asking price | official published rate | user-supplied assumption | cited source
    citation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "kind": self.kind,
            "basis": self.basis,
            "citation": self.citation,
        }


@dataclass
class LandedCostResult:
    currency: str
    qty: int
    lines: list[CostLine] = field(default_factory=list)
    landed_unit: float = 0.0
    landed_total: float = 0.0
    disclosures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "qty": self.qty,
            "lines": [line.as_dict() for line in self.lines],
            "landed_unit": self.landed_unit,
            "landed_total": self.landed_total,
            "disclosures": self.disclosures,
        }


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LandedCostError(f"{name} must be a number") from exc
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        raise LandedCostError(f"{name} must be a non-negative finite number")
    return number


def compute_landed_cost(
    *,
    unit_price: float,
    currency: str,
    qty: int = 1,
    shipping_total: float = 0.0,
    insurance: float = 0.0,
    duty_rate_pct: float = 0.0,
    flat_fees: float = 0.0,
    unit_price_basis: str | None = None,
    duty_basis: str | None = None,
    unit_price_kind: str = "estimate",
    duty_kind: str = "assumption",
    unit_price_citation: str | None = None,
    duty_citation: str | None = None,
) -> LandedCostResult:
    """Build the landed-cost template. Refuses invalid inputs; invents nothing.

    ``unit_price_kind/duty_kind`` decide the line KINDS; when the caller does
    not pass explicit BASIS strings they are derived from the kind (estimate
    -> asking price snapshot; observed -> official published rate;
    assumption -> user-supplied), so the two always tell the same story.
    """
    if not currency or not currency.strip():
        raise LandedCostError("currency is required (the template does not guess)")
    currency = currency.strip().upper()
    if qty < 1:
        raise LandedCostError("qty must be >= 1")
    price = _positive(unit_price, "unit_price")
    shipping = _positive(shipping_total, "shipping_total")
    ins = _positive(insurance, "insurance")
    duty_rate = _positive(duty_rate_pct, "duty_rate_pct")
    if duty_rate > 100:
        raise LandedCostError("duty_rate_pct must be <= 100 (a rate, not a price)")
    fees = _positive(flat_fees, "flat_fees")

    if duty_kind not in {"estimate", "observed", "assumption"}:
        raise LandedCostError(f"invalid duty_kind {duty_kind!r}")
    if unit_price_kind not in {"estimate", "observed", "assumption"}:
        raise LandedCostError(f"invalid unit_price_kind {unit_price_kind!r}")

    _KIND_BASIS = {
        "estimate": "asking price snapshot (estimate), not a live quote",
        "observed": "official published rate",
        "assumption": "user-supplied assumption",
    }
    unit_price_basis = unit_price_basis or _KIND_BASIS[unit_price_kind]
    duty_basis = duty_basis or _KIND_BASIS[duty_kind]

    duty_per_unit = price * duty_rate / 100.0
    shipping_per_unit = shipping / qty
    ins_per_unit = ins / qty
    fees_per_unit = fees / qty

    lines = [
        CostLine(
            "unit_price", "Asking price (per unit)", price, unit_price_kind,
            unit_price_basis, unit_price_citation,
        ),
        CostLine(
            "duty", f"Duty ({duty_rate:g}% of asking price)", duty_per_unit, duty_kind,
            duty_basis, duty_citation,
        ),
        CostLine(
            "shipping", f"Shipping (prorated, {shipping:g} / {qty})",
            shipping_per_unit, "assumption", "user-supplied assumption",
        ),
    ]
    if ins > 0:
        lines.append(
            CostLine(
                "insurance", f"Insurance (prorated, {ins:g} / {qty})",
                ins_per_unit, "assumption", "user-supplied assumption",
            )
        )
    if fees > 0:
        lines.append(
            CostLine(
                "flat_fees", f"Other fees (prorated, {fees:g} / {qty})",
                fees_per_unit, "assumption", "user-supplied assumption",
            )
        )

    landed_unit = price + duty_per_unit + shipping_per_unit + ins_per_unit + fees_per_unit
    landed_total = landed_unit * qty

    result = LandedCostResult(
        currency=currency,
        qty=qty,
        lines=lines,
        landed_unit=round(landed_unit, 2),
        landed_total=round(landed_total, 2),
    )
    result.disclosures.extend(
        [
            "landed cost is an ESTIMATE built from asking-price snapshots and "
            "user-supplied assumptions; it is not a quotation",
            "no verified transaction cost exists in this pipeline - asking "
            "prices and published rates are not paid invoices",
        ]
    )
    if duty_kind != "observed":
        result.disclosures.append(
            "duty was not bound to an official published rate, so it is typed "
            "as an assumption"
        )
    return result


__all__ = ["CostLine", "LandedCostError", "LandedCostResult", "compute_landed_cost"]
