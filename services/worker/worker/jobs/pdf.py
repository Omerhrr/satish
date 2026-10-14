"""WeasyPrint PDF report generation job.

Renders an HTML template to PDF via WeasyPrint and stores it through the
storage backend, then flips the artifact row to ``ready``. This is the
Documents tool category from the plan (docs.generate_pdf).
"""

from __future__ import annotations

import asyncio
import html
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.db import get_session_factory
from xp_core.logging import get_logger, setup_logging
from xp_core.models.entities import Artifact
from xp_core.services.storage import LocalStorage

log = get_logger(__name__)

_HTML_SHELL = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 2cm 2.2cm;
    @bottom-center {{ content: "XP — page " counter(page) " of " counter(pages);
                      font-size: 9px; color: #8a8f98; }} }}
  body {{ font-family: "DejaVu Sans", sans-serif; color: #14181f; line-height: 1.55; }}
  .brand {{ color: #f7931a; font-weight: 700; letter-spacing: 2px; font-size: 12px; }}
  h1 {{ font-size: 24px; margin: 6px 0 2px; }}
  .meta {{ color: #6b7280; font-size: 11px; margin-bottom: 22px; }}
  h2 {{ font-size: 16px; border-bottom: 2px solid #f7931a; padding-bottom: 4px;
        margin-top: 26px; }}
  .placeholder {{ color: #6b7280; font-size: 12px; }}
  .disclaimer {{ margin-top: 34px; padding: 10px 12px; background: #f6f7f9;
                 border-left: 3px solid #f7931a; font-size: 10.5px; color: #4b5563; }}
</style>
</head>
<body>
  <div class="brand">XP · BITCOIN-NATIVE AI WORKFORCE</div>
  <h1>{title}</h1>
  <div class="meta">Generated {generated_at} · artifact {artifact_id}</div>
  {sections_html}
  <div class="disclaimer">
    Scaffold demo artifact. Research reports produced by the full agent runtime will
    cite sources, record retrieval times, and separate observed facts from estimates.
    XP is an internal usage credit — it is not Bitcoin and not a blockchain token.
  </div>
</body>
</html>
"""


def _render_html(title: str, sections: list[str], artifact_id: str) -> str:
    sections_html = "".join(
        f"<h2>{html.escape(s)}</h2><p class='placeholder'>"
        "Content will be produced by the DSH agent runtime in a later phase."
        "</p>"
        for s in sections
    )
    return _HTML_SHELL.format(
        title=html.escape(title),
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        artifact_id=html.escape(artifact_id),
        sections_html=sections_html,
    )


def _render_and_store(
    artifact_id: str,
    title: str,
    sections: list[str],
) -> dict[str, Any]:
    """CPU-bound render + storage write; runs in a thread via asyncio.to_thread."""
    from weasyprint import HTML  # imported lazily: heavy import

    settings = get_settings()
    pdf_bytes = HTML(string=_render_html(title, sections, artifact_id)).write_pdf()

    storage = LocalStorage(settings.artifact_dir)
    key = f"reports/{artifact_id}/report.pdf"
    stored = storage.save_bytes(key, pdf_bytes)
    return {"object_key": key, "size_bytes": stored.size_bytes, "sha256": stored.sha256}


async def generate_pdf_report(
    ctx: dict[str, Any],
    *,
    artifact_id: str,
    title: str,
    sections: list[str],
    metadata: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Arq job function (also called inline by the dev bridge)."""
    setup_logging(get_settings().log_level)
    log.info("pdf_job_started", artifact_id=artifact_id, title=title)

    try:
        stored = await asyncio.to_thread(_render_and_store, artifact_id, title, sections)
    except Exception:
        log.exception("pdf_job_failed", artifact_id=artifact_id)
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(Artifact).where(Artifact.id == artifact_id))
            ).scalar_one_or_none()
            if row is not None:
                row.status = "failed"
                await session.commit()
        raise

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(select(Artifact).where(Artifact.id == artifact_id))
        ).scalar_one_or_none()
        if row is not None:
            row.status = "ready"
            row.size_bytes = stored["size_bytes"]
            row.sha256 = stored["sha256"]
            row.object_key = stored["object_key"]
            await session.commit()
    log.info("pdf_job_completed", artifact_id=artifact_id, size=stored["size_bytes"])
    return stored
