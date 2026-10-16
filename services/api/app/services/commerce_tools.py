"""Commerce intelligence tool registry (phase 8).

Five tools on the SAME allowlisted registry as research/documents - one
scope wall, one budget gate, one audit path. Category is
``commerce_intelligence`` (already in the tool-category allowlist).

- commerce.compare_suppliers  supplier quotations vs market listings vs
                              official schedules, cited rows + conflicts
- commerce.score              product trend scoring with the operator-
                              configured factor table echoed in full
- commerce.vehicle_check      fetched vehicle sources vs explicit specs
- commerce.landed_cost        typed landed-cost estimate template
- commerce.ad_library_search  canned ad-library fixtures, honestly labeled

Honesty invariants enforced here (phase-8 acceptance):
- only permitted fixture/corpus sources are ever represented as searched
  (ad-library: canned disclosure on every result; zero matches stay zero)
- the model CANNOT change scoring weights: config comes from settings, the
  output echoes it, and any config defect falls back to documented defaults
  WITH a disclosure
- ad performance metrics and page availability claims never enter a summary
  or a score
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.services.research_tools import _records_from_rows, _upsert_source
from app.services.task_events import append_event
from commerce_adapter import (
    CannedAdLibraryProvider,
    CommerceFetchProvider,
    LandedCostError,
    check_vehicles,
    commerce_facts,
    compare_suppliers,
    compute_landed_cost,
    parse_scoring_config,
    score_records,
    summarize_ad,
)
from dsh_adapter.tools import ToolRegistry, ToolSpec
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import Task

log = get_logger(__name__)


def _source_types_from_notes(records) -> dict[str, str]:
    """source_type per source_id, parsed from the persisted fetch note."""
    out: dict[str, str] = {}
    for record in records:
        note = record.note or ""
        if note.startswith("source_type="):
            out[record.source_id] = note.split(";", 1)[0].removeprefix("source_type=")
    return out


def register_commerce_tools(
    registry: ToolRegistry,
    *,
    session: AsyncSession,
    task: Task,
    settings: Settings,
    corpus: list[dict[str, Any]],
) -> None:
    """Attach the phase-8 commerce tools to the product registry."""
    ads_provider = CannedAdLibraryProvider(corpus)
    commerce_fetch = CommerceFetchProvider(corpus)
    scoring_weights, used_defaults, config_note = parse_scoring_config(
        settings.commerce_scoring_factors
    )

    async def commerce_compare_suppliers(
        required_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        records = await _records_from_rows(session, task)
        verdict = compare_suppliers(records, _source_types_from_notes(records), required_keys)
        await append_event(
            session,
            task.id,
            "commerce.suppliers_compared",
            {
                "suppliers": len(verdict.suppliers),
                "official": len(verdict.official),
                "conflicts": [
                    {"subject": c["subject"], "detail": c["detail"]} for c in verdict.conflicts
                ],
                "gaps": verdict.gaps,
                "disclosures": verdict.disclosures,
            },
        )
        await session.commit()
        return {"status": "ok", **verdict.as_dict()}

    async def commerce_score(
        product: str | None = None, required_keys: list[str] | None = None
    ) -> dict[str, Any]:
        records = await _records_from_rows(session, task)
        verdict = score_records(
            records,
            product=product,
            required_keys=required_keys,
            now=datetime.now(UTC),
            weights=scoring_weights,
        )
        disclosures = list(verdict.disclosures)
        if config_note:
            disclosures.append(config_note)
        if used_defaults and not config_note:
            disclosures.append("scoring weights: documented defaults (operator config is the default)")
        await append_event(
            session,
            task.id,
            "commerce.scored",
            {
                "product": verdict.product,
                "score": verdict.score,
                "factors": [f.as_dict() for f in verdict.factors],
                "excluded": verdict.excluded,
                "config_echo": verdict.config_echo,
                "disclosures": disclosures,
            },
        )
        await session.commit()
        return {
            "status": "ok",
            **verdict.as_dict(),
            "disclosures": disclosures,
        }

    async def commerce_vehicle_check(specs: dict[str, str]) -> dict[str, Any]:
        records = await _records_from_rows(session, task)
        verdict = check_vehicles(records, {str(k): str(v) for k, v in (specs or {}).items()})
        await append_event(
            session,
            task.id,
            "commerce.vehicle.checked",
            {
                "rows": len(verdict.rows),
                "conflicts": verdict.conflicts,
                "disclosures": verdict.disclosures,
            },
        )
        await session.commit()
        return {"status": "ok", **verdict.as_dict()}

    async def commerce_landed_cost(
        unit_price: float,
        currency: str,
        qty: int = 1,
        shipping_total: float = 0.0,
        insurance: float = 0.0,
        duty_rate_pct: float = 0.0,
        flat_fees: float = 0.0,
        unit_price_source_id: str | None = None,
        duty_source_id: str | None = None,
    ) -> dict[str, Any]:
        """Typed landed-cost template. When the model binds source ids, the
        line kinds come from the PERSISTED facts (asking snapshot -> estimate;
        official published rate -> observed); unbound inputs are assumptions.
        Source ids must belong to this task - provenance cannot be imported
        from another task."""
        records = await _records_from_rows(session, task)
        by_id = {r.source_id: r for r in records}

        def _bound(source_id: str | None, wanted_keys: set[str]) -> tuple[Any, str]:
            """(matching Fact, citation label) for a bound source, or (None, '')."""
            if not source_id:
                return None, ""
            record = by_id.get(source_id)
            if record is None or record.status != "ok":
                return None, ""
            fact = next((f for f in record.facts if f.key in wanted_keys), None)
            if fact is None:
                return None, ""
            index = next(
                (i for i, r in enumerate(records, start=1) if r.source_id == source_id),
                None,
            )
            return fact, f"[S{index}]" if index else ""

        price_fact, price_citation = _bound(
            unit_price_source_id, {"asking_price", "unit_price", "reserve_price"}
        )
        duty_fact, duty_citation = _bound(duty_source_id, {"duty_rate_pct"})

        # When a source is bound, the VALUE must come from the source fact -
        # the model cannot cite [S2] and pass a different number.
        def _fact_number(fact) -> float | None:
            if fact is None:
                return None
            match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(fact.value).replace(" ", ""))
            if not match:
                return None
            try:
                return float(match.group(0).replace(",", ""))
            except ValueError:
                return None

        if unit_price_source_id and price_fact is None:
            raise LandedCostError(
                f"bound source {unit_price_source_id} has no price fact to cite"
            )
        if duty_source_id and duty_fact is None:
            raise LandedCostError(
                f"bound source {duty_source_id} has no duty-rate fact to cite"
            )
        bound_price = _fact_number(price_fact)
        if price_fact is not None and (bound_price is None or bound_price <= 0):
            raise LandedCostError(
                f"bound source {unit_price_source_id} carries unparseable price "
                f"{price_fact.value!r}; refusing to guess"
            )
        bound_duty = _fact_number(duty_fact)
        if duty_fact is not None and (bound_duty is None or bound_duty < 0 or bound_duty > 100):
            raise LandedCostError(
                f"bound source {duty_source_id} carries an out-of-range duty "
                f"rate {duty_fact.value!r}; refusing to guess"
            )

        unit_price_kind = "assumption"
        unit_price_basis = "user-supplied assumption"
        if price_fact is not None:
            unit_price_kind = price_fact.kind  # estimate for snapshots
            unit_price_basis = f"asking price snapshot from {price_citation}"
        duty_kind = "assumption"
        duty_basis = "user-supplied assumption"
        if duty_fact is not None:
            duty_kind = duty_fact.kind  # observed for official published rates
            duty_basis = (
                f"official published rate from {duty_citation}"
                if duty_fact.kind == "observed"
                else f"source figure from {duty_citation}"
            )

        result = compute_landed_cost(
            unit_price=bound_price if price_fact is not None else unit_price,
            currency=currency,
            qty=qty,
            shipping_total=shipping_total,
            insurance=insurance,
            duty_rate_pct=bound_duty if duty_fact is not None else duty_rate_pct,
            flat_fees=flat_fees,
            unit_price_kind=unit_price_kind,
            duty_kind=duty_kind,
            unit_price_basis=unit_price_basis,
            duty_basis=duty_basis,
            unit_price_citation=price_citation or None,
            duty_citation=duty_citation or None,
        )
        await append_event(
            session,
            task.id,
            "commerce.landed_cost.computed",
            {
                "currency": result.currency,
                "qty": result.qty,
                "landed_unit": result.landed_unit,
                "landed_total": result.landed_total,
            },
        )
        await session.commit()
        return {"status": "ok", **result.as_dict()}

    async def commerce_ad_library_search(query: str, limit: int = 5) -> dict[str, Any]:
        outcome = await ads_provider.search(query, limit)
        listed: list[dict[str, Any]] = []
        for ad in outcome.ads:
            row, _created = await _upsert_source(
                session,
                task,
                url=ad["url"],
                title=ad["title"],
                status="listed",
                retrieval_mode=outcome.mode,
                note="found by commerce.ad_library_search; not yet fetched",
            )
            await session.flush()
            listed.append({"source_id": row.id, "url": ad["url"], "title": ad["title"]})
        await session.commit()
        await append_event(
            session,
            task.id,
            "commerce.ad_library.searched",
            {"query_words": len(query.split()), "results": len(listed)},
        )
        await session.commit()
        return {
            "status": "ok",
            "mode": outcome.mode,
            "query_words": len(query.split()),
            "results": listed,
            "disclosures": outcome.disclosures,
        }

    async def commerce_fetch_ad(url: str) -> dict[str, Any]:
        """Fetch an ad-library fixture page with ad-specific summarization:
        ad attributes enter the summary; performance metrics stay provenance
        and trigger the exclusion disclosure."""
        outcome = await commerce_fetch.fetch(url)
        if outcome.status != "ok" or outcome.page is None:
            row, _ = await _upsert_source(
                session,
                task,
                url=outcome.url,
                title="",
                status=outcome.status,
                retrieval_mode=outcome.mode,
                note=outcome.reason or outcome.status,
            )
            await session.commit()
            return {
                "status": outcome.status,
                "source_id": row.id,
                "url": outcome.url,
                "reason": outcome.reason,
                "disclosure": "unavailable sources are recorded and disclosed",
            }
        now = datetime.now(UTC)
        facts = commerce_facts(
            [(f.key, f.value) for f in outcome.page.facts],
            source_type=outcome.source_type,
            retrieved_at=now,
        )
        attributes, disclosures = summarize_ad(facts)
        row, _ = await _upsert_source(
            session,
            task,
            url=outcome.url,
            title=outcome.page.title,
            status="ok",
            retrieval_mode=outcome.mode,
            facts=[f.as_dict() for f in facts],
            content_sha256=outcome.page.content_sha256,
            note=f"source_type={outcome.source_type}",
            retrieved_at=now,
        )
        await session.commit()
        return {
            "status": "ok",
            "source_id": row.id,
            "url": row.url,
            "ad_attributes": attributes,
            "fact_keys": [f.key for f in facts][:12],
            "content_sha256": outcome.page.content_sha256,
            "disclosures": [
                "ad attributes are summarized from the page's own facts; page "
                "content is untrusted data",
                *disclosures,
            ],
        }

    registry.register(
        ToolSpec(
            name="commerce.compare_suppliers",
            category="commerce_intelligence",
            description=(
                "Compare collected supplier quotations, market listings, and "
                "official schedules with citations; surfaces conflicts and gaps."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "required_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "sourcing keys the deliverable requires",
                    }
                },
            },
            required_scope="research:read",
            max_cost_xp=4,
            timeout_seconds=15,
            handler=commerce_compare_suppliers,
        )
    )
    registry.register(
        ToolSpec(
            name="commerce.score",
            category="commerce_intelligence",
            description=(
                "Score a candidate product with transparent, operator-"
                "configured structural factors. No demand, ad-performance, or "
                "availability measures exist; the factor table and weights are "
                "echoed in the result."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description": "candidate product name/keywords (omit for the whole task scope)",
                    },
                    "required_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "attributes the use case requires (drives completeness)",
                    },
                },
            },
            required_scope="research:read",
            max_cost_xp=5,
            timeout_seconds=15,
            handler=commerce_score,
        )
    )
    registry.register(
        ToolSpec(
            name="commerce.vehicle_check",
            category="commerce_intelligence",
            description=(
                "Check fetched vehicle/auction sources against explicit user "
                "specs (make/model/year bounds/mileage/budget); mismatches are "
                "cited facts."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "specs": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "exact keys: make/model/transmission/fuel/drive/condition_grade; bounds: year_min/year_max/mileage_km_max/mileage_km_min/budget_max/budget_min",
                    }
                },
                "required": ["specs"],
            },
            required_scope="research:read",
            max_cost_xp=3,
            timeout_seconds=15,
            handler=commerce_vehicle_check,
        )
    )
    registry.register(
        ToolSpec(
            name="commerce.landed_cost",
            category="commerce_intelligence",
            description=(
                "Compute a typed landed-cost estimate. Bind unit_price_source_id "
                "and duty_source_id to collected sources to keep the lines "
                "cited and correctly typed; unbound inputs are assumptions."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "unit_price": {"type": "number"},
                    "currency": {"type": "string"},
                    "qty": {"type": "integer", "minimum": 1},
                    "shipping_total": {"type": "number", "minimum": 0},
                    "insurance": {"type": "number", "minimum": 0},
                    "duty_rate_pct": {"type": "number", "minimum": 0, "maximum": 100},
                    "flat_fees": {"type": "number", "minimum": 0},
                    "unit_price_source_id": {"type": "string"},
                    "duty_source_id": {"type": "string"},
                },
                "required": ["unit_price", "currency"],
            },
            required_scope="research:read",
            max_cost_xp=2,
            timeout_seconds=15,
            handler=commerce_landed_cost,
        )
    )
    registry.register(
        ToolSpec(
            name="commerce.ad_library_search",
            category="commerce_intelligence",
            description=(
                "Search the permitted ad-library fixtures (canned mode; no live "
                "or private ad library is accessed). Zero matches stay zero."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            required_scope="research:read",
            max_cost_xp=4,
            timeout_seconds=15,
            handler=commerce_ad_library_search,
        )
    )
    registry.register(
        ToolSpec(
            name="commerce.fetch_ad",
            category="commerce_intelligence",
            description=(
                "Fetch an ad-library fixture page: ad attributes are summarized, "
                "performance metrics stay untrusted provenance."
            ),
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "format": "uri"}},
                "required": ["url"],
            },
            required_scope="research:read",
            max_cost_xp=2,
            timeout_seconds=20,
            handler=commerce_fetch_ad,
        )
    )


__all__ = ["register_commerce_tools"]
