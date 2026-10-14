"""Artifact endpoints incl. the WeasyPrint PDF demo wired to the worker.

Storage is private-by-default: downloads go through this authorized route,
never a public object path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.models.entities import Artifact
from xp_core.schemas.api import ArtifactOut, DemoPdfIn
from xp_core.services.storage import LocalStorage

from app.deps import CurrentUser, DbSession
from app.worker_bridge import enqueue_pdf_job

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _artifact_out(a: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=a.id,
        object_key=a.object_key,
        content_type=a.content_type,
        size_bytes=a.size_bytes,
        sha256=a.sha256,
        status=a.status,
        download_url=f"/api/v1/artifacts/{a.id}/download" if a.status == "ready" else None,
        created_at=a.created_at,
    )


@router.post("/demo-pdf", response_model=ArtifactOut, status_code=status.HTTP_202_ACCEPTED)
async def create_demo_pdf(payload: DemoPdfIn, user: CurrentUser, session: DbSession) -> ArtifactOut:
    """Queue a demo PDF report rendered with WeasyPrint.

    With Redis configured the job runs on the arq worker; without Redis
    (local dev) it executes inline in a worker thread.
    """
    artifact = Artifact(
        user_id=user.id,
        object_key=f"demo/{user.id}/report-{payload.title.replace(' ', '-').lower()}.pdf",
        content_type="application/pdf",
        status="pending",
    )
    session.add(artifact)
    await session.flush()
    # Commit BEFORE enqueueing: the worker runs in its own session/transaction
    # and must be able to see (and flip) the durable artifact row.
    await session.commit()
    await enqueue_pdf_job(
        artifact_id=artifact.id,
        title=payload.title,
        sections=payload.sections,
        metadata=payload.metadata,
        user_id=user.id,
    )
    await session.refresh(artifact)
    return _artifact_out(artifact)


@router.get("", response_model=list[ArtifactOut])
async def list_artifacts(user: CurrentUser, session: DbSession) -> list[ArtifactOut]:
    rows = await session.execute(
        select(Artifact)
        .where(Artifact.user_id == user.id)
        .order_by(Artifact.created_at.desc())
        .limit(100)
    )
    return [_artifact_out(a) for a in rows.scalars()]


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(artifact_id: str, user: CurrentUser, session: DbSession) -> ArtifactOut:
    artifact = (
        await session.execute(
            select(Artifact).where(Artifact.id == artifact_id, Artifact.user_id == user.id)
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    return _artifact_out(artifact)


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: str, user: CurrentUser, session: DbSession
) -> FileResponse:
    artifact = (
        await session.execute(
            select(Artifact).where(Artifact.id == artifact_id, Artifact.user_id == user.id)
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    if artifact.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"artifact is {artifact.status}"
        )
    settings = get_settings()
    storage = LocalStorage(settings.artifact_dir)
    path = storage.open_path(artifact.object_key)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="artifact object missing")
    filename = artifact.object_key.rsplit("/", 1)[-1]
    return FileResponse(path, media_type=artifact.content_type, filename=filename)
