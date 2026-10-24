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

AI_QUEUE = "satish:ai"


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
        except Exception as exc:
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


async def enqueue_receipt_pdf_job(*, artifact_id: str, purchase_id: str) -> str:
    """Receipt rendering; same dual transport as the report job."""
    settings = get_settings()
    if settings.redis_url:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            job = await pool.enqueue_job(
                "generate_receipt_pdf", artifact_id=artifact_id, purchase_id=purchase_id
            )
            await pool.close()
            assert job is not None
            return job.job_id
        except Exception as exc:
            log.error("arq_enqueue_failed_falling_back_inline", error=str(exc))

    from worker.jobs.receipt import generate_receipt_pdf

    result = generate_receipt_pdf({}, artifact_id=artifact_id, purchase_id=purchase_id)
    if inspect.iscoroutine(result):
        result = await result
    return f"inline:{artifact_id}"


async def enqueue_agent_task_job(*, task_id: str, resume: bool = False) -> str:
    """Agent execution; same dual transport. Inline dev runs to completion."""
    settings = get_settings()
    if settings.redis_url:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            # Own queue + own worker: AI tasks never wait behind the minute-by-minute sweeps.
            job = await pool.enqueue_job(
                "run_agent_task_job", task_id=task_id, resume=resume, _queue_name=AI_QUEUE
            )
            await pool.close()
            assert job is not None
            return job.job_id
        except Exception as exc:
            log.error("arq_enqueue_failed_falling_back_inline", error=str(exc))

    from worker.jobs.agent import run_agent_task_job

    result = run_agent_task_job({}, task_id=task_id, resume=resume)
    if inspect.iscoroutine(result):
        result = await result
    return f"inline:{task_id}"
