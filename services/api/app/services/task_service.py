"""Task budget lifecycle service (phase 5 acceptance #6 + task_charge_flow).

Rules implemented here, all deterministic backend code:

- Charge cap: actual usage can never exceed the approved budget. The ledger
  raises before any entry lands if it would (acceptance #6: "A task cannot
  exceed its approved XP budget without additional authorization").
- Additional authorization: raising a budget is a USER action through
  POST /tasks/{id}/increase-budget - it reserves the delta atomically with
  its own idempotency key and appends an audit event. The agent registry has
  no tool that reaches this function (proven by test), so the agent cannot
  grant itself more budget.
- Failed-task rule: a failed task releases its FULL unused reservation -
  the user is not charged for work the platform failed to deliver
  (pricing_requirements #6: clear failed-task rules). The release is an
  auditable reservation_release entry, never a history rewrite.
- Cancellation rule: same full release, marked cancelled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.logging import get_logger
from xp_core.models.entities import AuditEvent, Task
from xp_core.services import ledger

log = get_logger(__name__)


async def get_owned_task(session: AsyncSession, user_id: str, task_id: str) -> Task:
    task = (
        await session.execute(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


async def increase_budget(
    session: AsyncSession, *, user_id: str, task_id: str, additional_xp: int
) -> Task:
    """User-authorized budget increase: reserve the delta, raise the cap.

    Idempotency key binds (task, resulting total) so a retried request with
    the same target total replays harmlessly, while a second, deliberate
    increase gets a fresh key.
    """
    if additional_xp <= 0:
        raise ValueError("additional_xp must be positive")
    task = await get_owned_task(session, user_id, task_id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=409, detail=f"cannot increase budget on a {task.status} task"
        )
    new_total = task.budget_xp + additional_xp
    try:
        await ledger.reserve_budget(
            session,
            user_id=user_id,
            task_id=task_id,
            amount=additional_xp,
            idempotency_key=f"reserve:inc:{task_id}:{new_total}",
        )
    except ledger.LedgerError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=402, detail=f"budget increase failed: {exc}"
        ) from exc
    task.budget_xp = new_total
    task.reserved_xp = new_total
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user_id,
            event_type="task.budget_increased",
            resource_type="task",
            resource_id=task_id,
            metadata_redacted={
                "additional_xp": additional_xp,
                "new_budget_xp": new_total,
            },
        )
    )
    await session.commit()
    await session.refresh(task)
    return task


async def settle_task_usage(
    session: AsyncSession, *, user_id: str, task_id: str, actual_xp: int
) -> Task:
    """Settle a task: charge actual usage within the cap, release the unused hold.

    Called by the worker at the end of a run (phase 6) and exposed as a
    system seam for tests/ops. actual_xp > budget_xp is refused by the
    ledger BEFORE anything is written - the approved cap is a hard ceiling.
    """
    task = await get_owned_task(session, user_id, task_id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"task already {task.status}")
    if actual_xp > task.budget_xp:
        raise HTTPException(
            status_code=409,
            detail=(
                f"actual_xp {actual_xp} exceeds the approved budget {task.budget_xp}; "
                "increase the budget first (user authorization required)"
            ),
        )
    try:
        await ledger.settle_task(
            session,
            user_id=user_id,
            task_id=task_id,
            reserved_xp=task.reserved_xp,
            actual_xp=actual_xp,
        )
    except ledger.LedgerError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"settlement refused: {exc}") from exc
    task.reserved_xp = 0
    task.actual_xp = actual_xp
    task.status = "completed"
    task.completed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor_type="system",
            event_type="task.settled",
            resource_type="task",
            resource_id=task_id,
            metadata_redacted={"actual_xp": actual_xp, "budget_xp": task.budget_xp},
        )
    )
    await session.commit()
    await session.refresh(task)
    log.info("task_settled", task_id=task_id, actual_xp=actual_xp)
    return task


async def fail_task(session: AsyncSession, *, user_id: str, task_id: str, reason: str) -> Task:
    """Failed-task rule: release the full unused reservation; charge nothing."""
    task = await get_owned_task(session, user_id, task_id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"task already {task.status}")
    released = task.reserved_xp
    if released > 0:
        await ledger.release_reservation(
            session, user_id=user_id, task_id=task_id, amount=released
        )
        task.reserved_xp = 0
    task.status = "failed"
    task.error = reason[:2000] if reason else None
    task.completed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            actor_type="system",
            event_type="task.failed",
            resource_type="task",
            resource_id=task_id,
            metadata_redacted={"released_xp": released, "reason": (reason or "")[:500]},
        )
    )
    await session.commit()
    await session.refresh(task)
    log.info("task_failed_released", task_id=task_id, released=released)
    return task


async def build_task_result(
    session: AsyncSession, *, user_id: str, task_id: str
) -> Any:
    """Explicit task result: deliverable, artifacts, provenance, limitations,
    and the XP receipt (phase-7 acceptance #4).

    Derived entirely from durable rows - no hidden state: artifacts and
    research sources by task, the latest research.compared verdict, the
    evaluation notes, and the ledger entries that reference the task.
    """
    from commerce_adapter import confidence_label, freshness_label
    from research_adapter import SourceRecord
    from xp_core.models.entities import (
        Artifact,
        ResearchSource,
        TaskEvent,
        XpLedgerEntry,
    )
    from xp_core.schemas.api import (
        ResultArtifactOut,
        ResultSourceOut,
        ScoredFactorOut,
        ScoredOut,
        TaskResultOut,
        XpReceiptOut,
    )

    task = await get_owned_task(session, user_id, task_id)

    artifact_rows = (
        await session.execute(
            select(Artifact)
            .where(Artifact.task_id == task.id, Artifact.status == "ready")
            .order_by(Artifact.created_at)
        )
    ).scalars().all()
    artifacts = [
        ResultArtifactOut(
            id=a.id,
            filename=a.object_key.rsplit("/", 1)[-1],
            content_type=a.content_type,
            size_bytes=a.size_bytes,
            sha256=a.sha256,
            download_url=f"/api/v1/artifacts/{a.id}/download",
        )
        for a in artifact_rows
    ]

    source_rows = (
        await session.execute(
            select(ResearchSource)
            .where(ResearchSource.task_id == task.id)
            .order_by(ResearchSource.created_at)
        )
    ).scalars().all()
    sources = []
    for s in source_rows:
        record = SourceRecord(
            source_id=s.id,
            url=s.url,
            title=s.title,
            status=s.status,
            retrieved_at=s.retrieved_at,
            retrieval_mode=s.retrieval_mode,
            note=s.note,
        )
        conf_label, _rationale, _score = confidence_label(record)
        sources.append(
            ResultSourceOut(
                url=s.url,
                title=s.title,
                status=s.status,
                retrieval_mode=s.retrieval_mode,
                fact_count=s.fact_count,
                retrieved_at=s.retrieved_at,
                note=s.note,
                freshness=freshness_label(s.retrieved_at),
                confidence=conf_label,
            )
        )

    compared = (
        await session.execute(
            select(TaskEvent)
            .where(
                TaskEvent.task_id == task.id, TaskEvent.event_type == "research.compared"
            )
            .order_by(TaskEvent.seq.desc())
            .limit(1)
        )
    ).scalars().first()
    conflicts: list[dict[str, Any]] = []
    gaps: list[str] = []
    disclosures: list[str] = []
    if compared is not None:
        payload = compared.payload or {}
        conflicts = list(payload.get("conflicts", []))
        gaps = list(payload.get("gaps", []))
        disclosures = list(payload.get("disclosures", []))

    # phase-8: latest commerce.scored verdict (factor table + config echo)
    scored_event = (
        await session.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id, TaskEvent.event_type == "commerce.scored")
            .order_by(TaskEvent.seq.desc())
            .limit(1)
        )
    ).scalars().first()
    scored: ScoredOut | None = None
    if scored_event is not None:
        payload = scored_event.payload or {}
        scored = ScoredOut(
            product=str(payload.get("product", "")),
            score=float(payload.get("score", 0.0)),
            factors=[
                ScoredFactorOut(
                    name=str(f.get("name", "")),
                    weight=float(f.get("weight", 0.0)),
                    signal=str(f.get("signal", "")),
                    normalized=(
                        float(f["normalized"]) if f.get("normalized") is not None else None
                    ),
                    included=bool(f.get("included", False)),
                    reason=str(f.get("reason", "")),
                )
                for f in payload.get("factors", [])
                if isinstance(f, dict)
            ],
            excluded=[str(e) for e in payload.get("excluded", [])],
            config_echo={
                str(k): float(v) for k, v in (payload.get("config_echo") or {}).items()
            },
            disclosures=[str(d) for d in payload.get("disclosures", [])],
        )

    evaluation = (
        await session.execute(
            select(TaskEvent)
            .where(
                TaskEvent.task_id == task.id,
                TaskEvent.event_type == "evaluation.completed",
            )
            .order_by(TaskEvent.seq.desc())
            .limit(1)
        )
    ).scalars().first()
    limitations = list(disclosures)
    if evaluation is not None:
        limitations.extend(str(n) for n in (evaluation.payload or {}).get("notes", []))
    limitations.extend(
        f"source {s.url} is {s.status}: {s.note or 'no reason recorded'}"
        for s in source_rows
        if s.status in {"unavailable", "denied", "error"}
    )

    # XP receipt from the ledger - the append-only trail IS the receipt.
    entries = (
        await session.execute(
            select(XpLedgerEntry)
            .where(
                XpLedgerEntry.reference_type == "task",
                XpLedgerEntry.reference_id == task.id,
                XpLedgerEntry.entry_type.in_(
                    {"reservation", "reservation_release", "charge"}
                ),
            )
            .order_by(XpLedgerEntry.created_at)
        )
    ).scalars().all()
    charge = next((e for e in entries if e.entry_type == "charge"), None)
    if task.status == "completed" and charge is not None:
        receipt_status = "settled"
        released = task.budget_xp - task.actual_xp
    elif task.status in {"failed", "cancelled"}:
        receipt_status = "no_charge"
        released = task.budget_xp
    else:
        receipt_status = "pending_settlement"
        released = 0
    receipt = XpReceiptOut(
        budget_xp=task.budget_xp,
        actual_xp=task.actual_xp,
        released_xp=released,
        charge_entry_id=charge.id if charge else None,
        settled_at=charge.created_at if charge else None,
        balance_after=charge.balance_after if charge else None,
        status=receipt_status,
    )

    done_event = (
        await session.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id, TaskEvent.event_type == "task.completed")
            .order_by(TaskEvent.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    answer = ((done_event.payload or {}).get("answer") if done_event else None) or None

    return TaskResultOut(
        task_id=task.id,
        status=task.status,
        objective=task.objective,
        answer=answer,
        deliverable=task.deliverable,
        completed_at=task.completed_at,
        artifacts=artifacts,
        sources=sources,
        conflicts=conflicts,
        gaps=gaps,
        limitations=limitations,
        xp_receipt=receipt,
        scored=scored,
    )


__all__ = [
    "build_task_result",
    "fail_task",
    "get_owned_task",
    "increase_budget",
    "settle_task_usage",
]
