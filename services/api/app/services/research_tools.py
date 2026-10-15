"""Product tool registry (phase 7): real research + document tools.

Replaces the phase-6 scaffold stubs at runtime. The model still only ever
sees typed, allowlisted tools — but the handlers now do the real work:

- web.search        canned provider over the committed evaluation corpus;
                    every listing persisted as a ResearchSource row
- web.fetch_page    FetchPolicy-gated retrieval (canned or http per config);
                    facts extracted, typed, persisted; output to the model
                    is SHAPE ONLY (ids/counts/keys), never raw page content
- research.compare  cross-source comparison -> conflicts, gaps, disclosures;
                    a research.compared event persists the verdict
- docs.generate_pdf cited report through the quality gates; refusing to
                    render uncited claims (DocumentQualityError)
- docs.generate_csv / docs.generate_xlsx  cited comparison table exports
- email/automation  unchanged stubs (their product surfaces arrive later)

Unchanged invariants: scope wall, budget gate, timeouts, audit records,
and NO key material anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.task_events import append_event
from dsh_adapter.tools import ToolRegistry, ToolSpec
from research_adapter import (
    Fact,
    SourceRecord,
    compare_sources,
    facts_from_extraction,
    make_fetch_provider,
    make_search_provider,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.config import Settings
from xp_core.logging import get_logger
from xp_core.models.entities import Artifact, ResearchSource, Task
from xp_core.services.documents import (
    DocumentQualityError,
    ReportClaim,
    ReportSource,
    ReportSpec,
    build_csv,
    build_xlsx,
    render_report_pdf,
    validate_document,
)
from xp_core.services.storage import StorageBackend

log = get_logger(__name__)

RESEARCH_CORPUS_FALLBACK: list[dict[str, Any]] = []

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def load_corpus(settings: Settings) -> list[dict[str, Any]]:
    """The evaluation corpus doubles as the canned provider's dataset."""
    import json
    from pathlib import Path

    path = Path(settings.research_eval_set_path)
    if not path.is_absolute():
        # Settings paths are repo-root relative (config.py convention).
        path = Path(__file__).resolve().parents[4] / path
    if not path.is_file():
        log.warning("research_corpus_missing", path=str(path))
        return RESEARCH_CORPUS_FALLBACK
    return json.loads(path.read_text())["corpus"]


async def _upsert_source(
    session: AsyncSession,
    task: Task,
    *,
    url: str,
    title: str,
    status: str,
    retrieval_mode: str,
    facts: list[dict[str, Any]] | None = None,
    content_sha256: str | None = None,
    note: str | None = None,
    retrieved_at: datetime | None = None,
) -> tuple[ResearchSource, bool]:
    """(task, url)-unique upsert: refetching upgrades a row, never duplicates."""
    row = (
        await session.execute(
            select(ResearchSource).where(
                ResearchSource.task_id == task.id, ResearchSource.url == url
            )
        )
    ).scalars().first()
    created = row is None
    if row is None:
        row = ResearchSource(task_id=task.id, user_id=task.user_id, url=url)
        session.add(row)
    # A fetch beats a bare listing; a later listing never downgrades a fetch.
    rank = {"listed": 0, "error": 1, "unavailable": 2, "denied": 3, "ok": 4}
    if not created and rank.get(row.status, 0) > rank.get(status, 0):
        return row, False
    row.title = title or row.title or ""
    row.status = status
    row.retrieval_mode = retrieval_mode
    row.facts = facts or ([] if created else row.facts)
    row.fact_count = len(facts or [])
    row.content_sha256 = content_sha256 or row.content_sha256
    row.note = note
    row.retrieved_at = retrieved_at
    return row, created


async def _records_from_rows(session: AsyncSession, task: Task) -> list[SourceRecord]:
    rows = (
        await session.execute(
            select(ResearchSource)
            .where(ResearchSource.task_id == task.id)
            .order_by(ResearchSource.created_at)
        )
    ).scalars().all()
    records: list[SourceRecord] = []
    for row in rows:
        records.append(
            SourceRecord(
                source_id=row.id,
                url=row.url,
                title=row.title,
                status=row.status,
                retrieved_at=row.retrieved_at,
                facts=[Fact.from_dict(f) for f in (row.facts or [])],
                content_sha256=row.content_sha256,
                retrieval_mode=row.retrieval_mode,
                note=row.note,
            )
        )
    return records


async def _citable_rows(session: AsyncSession, task: Task) -> list[ResearchSource]:
    """Sources eligible for the report appendix/citations, in stable order:
    fetched-ok first (citation-bearing), then listed, then unreachable."""
    rows = (
        await session.execute(
            select(ResearchSource)
            .where(ResearchSource.task_id == task.id)
            .order_by(ResearchSource.created_at)
        )
    ).scalars().all()
    rank = {"ok": 0, "listed": 1, "error": 2, "unavailable": 3, "denied": 4}
    return sorted(rows, key=lambda r: (rank.get(r.status, 9), r.created_at))


async def _build_report_spec(
    session: AsyncSession, task: Task, settings: Settings, title: str
) -> tuple[ReportSpec, list[SourceRecord]]:
    records = await _records_from_rows(session, task)
    rows = await _citable_rows(session, task)

    sources: list[ReportSource] = []
    index_of: dict[str, int] = {}
    for i, row in enumerate(rows, start=1):
        index_of[row.id] = i
        sources.append(
            ReportSource(
                index=i,
                url=row.url,
                title=row.title,
                status=row.status,
                retrieved_at=row.retrieved_at,
                fact_count=row.fact_count,
                retrieval_mode=row.retrieval_mode,
            )
        )

    claims: list[ReportClaim] = []
    for record in records:
        if record.status != "ok":
            continue
        index = index_of.get(record.source_id)
        if index is None:
            continue
        for fact in record.facts:
            text = f"{fact.key.replace('_', ' ')}: {fact.value}"
            if fact.note:
                text += f" ({fact.note})"
            claims.append(ReportClaim(text=text, citations=[index], kind=fact.kind))

    comparison = compare_sources(records)
    unavailable = [
        f"S{index_of[r.source_id]} {r.url} — {r.status}: {r.note or 'no reason recorded'}"
        for r in records
        if r.status in {"unavailable", "denied", "error"} and r.source_id in index_of
    ]

    limitations = [
        "claims reflect what the fetched pages said at retrieval time; the report "
        "does not verify factual truth beyond source agreement",
        "structural quality gates only — sources and claims remain the user's "
        "responsibility to review",
    ]
    if any(claim.kind == "estimate" for claim in claims):
        limitations.append(
            "some figures are listing snapshots (typed 'estimate') and must not be "
            "quoted as live prices"
        )
    if not records:
        limitations.append(
            "no sources were collected — this report contains disclosures only, "
            "no findings"
        )

    spec = ReportSpec(
        title=title,
        goal=task.objective,
        generated_at=datetime.now(UTC),
        claims=claims,
        conflicts=[
            {"subject": c.subject, "detail": c.detail, "values": c.values}
            for c in comparison.conflicts
        ],
        gaps=list(comparison.gaps),
        sources=sources,
        unavailable=unavailable,
        limitations=limitations,
        task_id=task.id,
        mode_notes=[
            f"search mode: {settings.research_search_mode} (canned results come from the "
            "committed offline evaluation corpus, not live web listings)",
            f"fetch mode: {settings.research_fetch_mode}",
            *comparison.disclosures,
        ],
    )
    return spec, records


async def _store_artifact(
    session: AsyncSession,
    task: Task,
    storage: StorageBackend,
    *,
    kind: str,
    content_type: str,
    data: bytes,
    filename: str,
) -> Artifact:
    ok, detail = validate_document(kind, data)  # type: ignore[arg-type]
    if not ok:
        raise DocumentQualityError(f"generated {kind} failed validation", [detail])
    artifact = Artifact(
        user_id=task.user_id,
        task_id=task.id,
        object_key=f"tasks/{task.id}/{filename}",
        content_type=content_type,
        status="pending",
    )
    session.add(artifact)
    await session.flush()
    stored = storage.save_bytes(artifact.object_key, data)
    artifact.size_bytes = stored.size_bytes
    artifact.sha256 = stored.sha256
    artifact.status = "ready"
    return artifact


def _comparison_table(records: list[SourceRecord]) -> tuple[list[str], list[list[Any]]]:
    comparison = compare_sources(records)
    headers = ["subject", "source", "url", "value", "kind", "note"]
    rows: list[list[Any]] = []
    for row in comparison.rows:
        for value in row.values:
            rows.append(
                [
                    row.subject,
                    value["citation"],
                    next(r.url for r in records if r.source_id == value["source_id"]),
                    value["value"],
                    value["kind"],
                    value["note"],
                ]
            )
    return headers, rows


def build_product_registry(
    *, session: AsyncSession, task: Task, settings: Settings, storage: StorageBackend
) -> ToolRegistry:
    """The runtime registry: same allowlist semantics, real handlers."""
    registry = ToolRegistry()
    corpus = load_corpus(settings)
    search_provider = make_search_provider(settings.research_search_mode, corpus)
    fetch_provider = make_fetch_provider(settings.research_fetch_mode, corpus)

    async def web_search(query: str, limit: int = 5) -> dict[str, Any]:
        outcome = await search_provider.search(query, limit)
        listed: list[dict[str, Any]] = []
        for listing in outcome.results:
            row, _created = await _upsert_source(
                session,
                task,
                url=listing.url,
                title=listing.title,
                status="listed",
                retrieval_mode=outcome.mode,
                note="found by web.search; not yet fetched",
            )
            await session.flush()
            listed.append({"source_id": row.id, "url": listing.url, "title": listing.title})
        await session.commit()
        return {
            "status": "ok",
            "mode": outcome.mode,
            "query_words": len(query.split()),
            "results": listed,
            "disclosure": outcome.disclosure,
        }

    async def web_fetch_page(url: str) -> dict[str, Any]:
        outcome = await fetch_provider.fetch(url)
        if outcome.status == "ok" and outcome.page is not None:
            facts = facts_from_extraction(
                [(f.key, f.value) for f in outcome.page.facts],
                is_listing_snapshot=outcome.is_listing_snapshot,
                retrieved_at=datetime.now(UTC),
            )
            row, _ = await _upsert_source(
                session,
                task,
                url=outcome.url,
                title=outcome.page.title,
                status="ok",
                retrieval_mode=outcome.mode,
                facts=[f.as_dict() for f in facts],
                content_sha256=outcome.page.content_sha256,
                retrieved_at=datetime.now(UTC),
            )
            await session.commit()
            fact_keys = [f.key for f in facts]
            return {
                "status": "ok",
                "source_id": row.id,
                "url": row.url,
                "title": row.title,
                "fact_count": len(facts),
                "fact_keys": fact_keys[:12],
                "content_sha256": outcome.page.content_sha256,
                "mode": outcome.mode,
                "disclosure": (
                    "page content was extracted server-side and stored as untrusted "
                    "data; only extracted fact keys are returned to the model"
                ),
            }
        # Every non-ok outcome is a durable, disclosable provenance record.
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
            "mode": outcome.mode,
            "reason": outcome.reason,
            "disclosure": "unavailable/denied sources are recorded and will be "
            "disclosed in the report",
        }

    async def research_compare(required_keys: list[str] | None = None) -> dict[str, Any]:
        records = await _records_from_rows(session, task)
        comparison = compare_sources(records, required_keys)
        await append_event(
            session,
            task.id,
            "research.compared",
            {
                "subjects": len(comparison.rows),
                "conflicts": [
                    {"subject": c.subject, "detail": c.detail} for c in comparison.conflicts
                ],
                "gaps": comparison.gaps,
                "disclosures": comparison.disclosures,
            },
        )
        await session.commit()
        return {
            "status": "ok",
            "subjects": [
                {"subject": r.subject, "conflict": r.conflict, "values": r.values}
                for r in comparison.rows
            ],
            "conflicts": [c.detail for c in comparison.conflicts],
            "gaps": comparison.gaps,
            "disclosures": comparison.disclosures,
        }

    async def docs_generate_pdf(title: str, sections: list[str] | None = None) -> dict[str, Any]:
        spec, _records = await _build_report_spec(session, task, settings, title)
        try:
            data = render_report_pdf(spec)
        except DocumentQualityError as exc:
            return {
                "status": "quality_gate_failed",
                "violations": exc.violations,
                "disclosure": "the report refused to render: claims must cite sources",
            }
        artifact = await _store_artifact(
            session,
            task,
            storage,
            kind="pdf",
            content_type="application/pdf",
            data=data,
            filename=f"report-{artifact_slug(title)}.pdf",
        )
        await session.commit()
        return {
            "status": "ok",
            "artifact_id": artifact.id,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "cited_claims": len(spec.claims),
            "sources": len(spec.sources),
            "limitations_count": len(spec.limitations) + len(spec.unavailable),
            "disclosure": "validated PDF stored privately; download via the "
            "authorized artifact route",
        }

    async def docs_generate_csv(title: str = "comparison") -> dict[str, Any]:
        records = await _records_from_rows(session, task)
        headers, rows = _comparison_table(records)
        data = build_csv(headers, rows)
        artifact = await _store_artifact(
            session,
            task,
            storage,
            kind="csv",
            content_type="text/csv",
            data=data,
            filename=f"{artifact_slug(title)}.csv",
        )
        await session.commit()
        return {
            "status": "ok",
            "artifact_id": artifact.id,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "data_rows": len(rows),
            "disclosure": "validated CSV stored privately",
        }

    async def docs_generate_xlsx(title: str = "comparison") -> dict[str, Any]:
        records = await _records_from_rows(session, task)
        headers, rows = _comparison_table(records)
        data = build_xlsx(title, headers, rows)
        artifact = await _store_artifact(
            session,
            task,
            storage,
            kind="xlsx",
            content_type=XLSX_CONTENT_TYPE,
            data=data,
            filename=f"{artifact_slug(title)}.xlsx",
        )
        await session.commit()
        return {
            "status": "ok",
            "artifact_id": artifact.id,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "data_rows": len(rows),
            "disclosure": "validated XLSX stored privately",
        }

    # -- communication / automation: unchanged stubs until their phases -------

    async def draft_email(to: str, subject: str, body: str) -> dict[str, Any]:
        return {"status": "drafted", "to": to, "subject": subject, "body": body}

    async def send_email(to: str, subject: str, body: str) -> dict[str, Any]:
        return {"status": "stub_requires_approval", "to": to, "subject": subject}

    async def schedule_job(schedule: str, objective: str) -> dict[str, Any]:
        return {"status": "stub", "schedule": schedule, "objective": objective}

    registry.register(
        ToolSpec(
            name="web.search",
            category="research",
            description="Search permitted public web sources and return ranked results.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
            required_scope="research:read",
            max_cost_xp=5,
            timeout_seconds=20,
            handler=web_search,
        )
    )
    registry.register(
        ToolSpec(
            name="web.fetch_page",
            category="research",
            description="Fetch a permitted public page for structured extraction.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "format": "uri"}},
                "required": ["url"],
            },
            required_scope="research:read",
            max_cost_xp=2,
            timeout_seconds=25,
            handler=web_fetch_page,
        )
    )
    registry.register(
        ToolSpec(
            name="research.compare",
            category="research",
            description="Compare collected sources: conflicts, gaps, disclosures.",
            input_schema={
                "type": "object",
                "properties": {
                    "required_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "fact keys the deliverable requires",
                    }
                },
            },
            required_scope="research:read",
            max_cost_xp=3,
            timeout_seconds=15,
            handler=research_compare,
        )
    )
    registry.register(
        ToolSpec(
            name="docs.generate_pdf",
            category="documents",
            description="Generate a cited PDF research report from collected sources.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "sections": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
            required_scope="documents:write",
            max_cost_xp=10,
            timeout_seconds=120,
            handler=docs_generate_pdf,
        )
    )
    registry.register(
        ToolSpec(
            name="docs.generate_csv",
            category="documents",
            description="Export the cited cross-source comparison table as CSV.",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
            required_scope="documents:write",
            max_cost_xp=6,
            timeout_seconds=60,
            handler=docs_generate_csv,
        )
    )
    registry.register(
        ToolSpec(
            name="docs.generate_xlsx",
            category="documents",
            description="Export the cited cross-source comparison table as XLSX.",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
            required_scope="documents:write",
            max_cost_xp=6,
            timeout_seconds=60,
            handler=docs_generate_xlsx,
        )
    )
    registry.register(
        ToolSpec(
            name="email.draft",
            category="communication",
            description="Draft an email for user review. Never sends.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
            required_scope="email:draft",
            max_cost_xp=1,
            timeout_seconds=15,
            handler=draft_email,
        )
    )
    registry.register(
        ToolSpec(
            name="email.send",
            category="communication",
            description="Send an email. REQUIRES explicit user approval first.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
            required_scope="email:send",
            max_cost_xp=2,
            timeout_seconds=30,
            requires_approval=True,
            handler=send_email,
        )
    )
    registry.register(
        ToolSpec(
            name="automation.schedule",
            category="automation",
            description="Create a scheduled research/monitoring job within granted scopes.",
            input_schema={
                "type": "object",
                "properties": {
                    "schedule": {"type": "string"},
                    "objective": {"type": "string"},
                },
                "required": ["schedule", "objective"],
            },
            required_scope="automation:write",
            max_cost_xp=3,
            timeout_seconds=15,
            requires_approval=True,
            handler=schedule_job,
        )
    )
    return registry


def artifact_slug(title: str) -> str:
    """Filename-safe slug; artifacts keep their full title in the report body."""
    keep = [c if c.isalnum() else "-" for c in title.lower().strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug.strip("-") or "artifact")[:60]


__all__ = ["artifact_slug", "build_product_registry", "load_corpus"]
