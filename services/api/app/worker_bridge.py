"""Bridge from API to worker jobs.

With XP_REDIS_URL configured, jobs are enqueued on the arq worker. Without
Redis (local dev / sandbox), the worker job function is imported and executed
inline in a thread so the full flow still works with zero infrastructure.
"""

from __future__ import annotations

import contextlib
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


async def _ai_worker_alive(settings) -> bool:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        try:
            return bool(await r.get(f"{AI_QUEUE}:alive") or await r.get(f"{AI_QUEUE}:health-check"))
        finally:
            await r.aclose()
    except Exception:
        return False


_background: set = set()  # keeps API-run tasks referenced until they finish


async def enqueue_agent_task_job(*, task_id: str, resume: bool = False) -> str:
    """Hand a task to the AI worker. If no AI worker is alive, run it in the
    background inside the API instead, so Satish AI keeps working either way
    (the job is still queued: whichever starts first runs it, exactly once)."""
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
            assert job is not None
            if not await _ai_worker_alive(settings):
                await pool.close()
                log.warning("ai_worker_offline_running_in_api", task_id=task_id)
                _run_in_background(task_id, resume)
                return f"api:{task_id}"
            # Safety net: if no worker has picked the job up within a few
            # seconds (whatever the reason), the API runs it instead.
            _watch_pickup(pool, job, task_id, resume)
            return job.job_id
        except Exception as exc:
            log.error("arq_enqueue_failed_running_in_api", error=str(exc))
            _run_in_background(task_id, resume)
            return f"api:{task_id}"

    from worker.jobs.agent import run_agent_task_job

    result = run_agent_task_job({}, task_id=task_id, resume=resume)
    if inspect.iscoroutine(result):
        result = await result
    return f"inline:{task_id}"


PICKUP_GRACE_SECONDS = 6


def _watch_pickup(pool, job, task_id: str, resume: bool) -> None:
    import asyncio

    from arq.jobs import JobStatus

    async def watch() -> None:
        try:
            await asyncio.sleep(PICKUP_GRACE_SECONDS)
            status = await job.status()
            if status in (JobStatus.queued, JobStatus.deferred):
                log.warning("ai_worker_did_not_pick_up_running_in_api", task_id=task_id, job_status=str(status))
                # If a worker picks it up later, the exactly-once claim makes it skip.
                _run_in_background(task_id, resume)
        except Exception as exc:
            log.error("pickup_watch_failed_running_in_api", task_id=task_id, error=str(exc))
            _run_in_background(task_id, resume)
        finally:
            with contextlib.suppress(Exception):
                await pool.close()

    t = asyncio.get_running_loop().create_task(watch())
    _background.add(t)
    t.add_done_callback(_background.discard)


def _run_in_background(task_id: str, resume: bool) -> None:
    import asyncio

    from worker.jobs.agent import run_agent_task_job

    async def go() -> None:
        try:
            await asyncio.wait_for(
                run_agent_task_job({}, task_id=task_id, resume=resume),
                timeout=get_settings().agent_task_timeout_seconds,
            )
        except Exception as exc:  # the watchdog returns the TK if this dies
            log.error("api_run_failed", task_id=task_id, error=str(exc))

    t = asyncio.get_running_loop().create_task(go())
    _background.add(t)
    t.add_done_callback(_background.discard)
