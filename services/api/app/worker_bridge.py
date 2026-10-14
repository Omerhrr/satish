"""Bridge from API to worker jobs.

With XP_REDIS_URL configured, jobs are enqueued on the arq worker. Without
Redis (local dev / sandbox), the worker job function is imported and executed
inline in a thread so the full flow still works with zero infrastructure.
"""

from __future__ import annotations

import inspect

from xp_core.config import get_settings
from xp_core.logging import get_logger

log = get_logger(__name__)


async def enqueue_pdf_job(
    *, artifact_id: str, title: str, sections: list[str], metadata: dict, user_id: str
) -> str:
    settings = get_settings()
    if settings.redis_url:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            job = await pool.enqueue_job(
                "generate_pdf_report",
                artifact_id=artifact_id,
                title=title,
                sections=sections,
                metadata=metadata,
                user_id=user_id,
            )
            await pool.close()
            assert job is not None
            return job.job_id
        except Exception as exc:  # noqa: BLE001 - fall back to inline execution
            log.error("arq_enqueue_failed_falling_back_inline", error=str(exc))

    # Inline dev execution (no Redis): run the same job function in a thread.
    from worker.jobs.pdf import generate_pdf_report

    ctx: dict = {}
    result = generate_pdf_report(
        ctx,
        artifact_id=artifact_id,
        title=title,
        sections=sections,
        metadata=metadata,
        user_id=user_id,
    )
    if inspect.iscoroutine(result):
        result = await result
    return f"inline:{artifact_id}"
