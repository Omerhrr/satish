"""arq WorkerSettings - run with: arq worker.settings.WorkerSettings"""

from __future__ import annotations

from typing import Any

from xp_core.config import get_settings
from xp_core.logging import setup_logging

from worker.jobs.agent import run_agent_task_job
from worker.jobs.automation import run_scheduled_jobs_job
from worker.jobs.pdf import generate_pdf_report
from worker.jobs.receipt import generate_receipt_pdf
from worker.jobs.relay import relay_notifications_job
from worker.jobs.retention import run_retention_sweep_job


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    ctx["settings"] = settings


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


async def scheduled_reconciliation(ctx: dict[str, Any]) -> dict[str, Any]:
    """billing_flow #8: scheduled reconciliation flags discrepancies.

    Runs on a fixed interval (XP_RECONCILE_INTERVAL_SECONDS, default 3600)
    whenever the worker has a database; discrepancies are audited by
    xp_core.jobs.reconciliation.reconcile_all itself.
    """
    from xp_core.db import get_session_factory
    from xp_core.jobs.reconciliation import reconcile_all

    factory = get_session_factory()
    async with factory() as session:
        return await reconcile_all(session)


async def onchain_payment_sweep(ctx: dict[str, Any]) -> dict[str, Any]:
    """Credit TK for on-chain payments that arrived (XP_PAYMENT_MODE=onchain)."""
    from xp_core.db import get_session_factory
    from xp_core.services.onchain import sweep

    settings = get_settings()
    if settings.payment_mode != "onchain":
        return {"skipped": "payment_mode is not onchain"}
    async with get_session_factory()() as session:
        return await sweep(session, settings)


async def payment_request_sweep(ctx: dict[str, Any]) -> dict[str, Any]:
    """Mark shareable payment requests paid and notify their owners."""
    from xp_core.db import get_session_factory
    from xp_core.services.handles import sweep_requests

    async with get_session_factory()() as session:
        return await sweep_requests(session, get_settings())


async def wallet_alert_sweep(ctx: dict[str, Any]) -> dict[str, Any]:
    """Queue Telegram messages for bitcoin arriving at watched wallet addresses."""
    from xp_core.db import get_session_factory
    from xp_core.services.wallet_alerts import sweep

    async with get_session_factory()() as session:
        return await sweep(session, get_settings())


async def stale_task_watchdog(ctx: dict[str, Any]) -> dict[str, Any]:
    """Stop AI tasks stuck in 'running' (killed run) and return their TK."""
    from app.services.agent_service import fail_stale_tasks
    from xp_core.db import get_session_factory

    return await fail_stale_tasks(get_session_factory(), get_settings())


def _build_cron_jobs() -> tuple:
    """Cron built lazily so import never requires settings resolution."""
    from arq.cron import cron

    interval = max(60, get_settings().reconcile_interval_seconds)
    # arq cron is minute-granular; approximate the interval in minutes.
    minutes = max(1, interval // 60)
    # Automation sweep (phase 9): due scheduled jobs get one decision each.
    sweep_minutes = max(1, get_settings().automation_sweep_interval_seconds // 60)
    # Notification relay (phase 9, KL-06): one push decision per notification.
    relay_minutes = max(1, get_settings().relay_sweep_interval_seconds // 60)
    return (
        cron(
            scheduled_reconciliation,
            minute=set(range(0, 60, minutes)) if minutes < 60 else None,
            run_at_startup=False,
        ),
        cron(
            run_scheduled_jobs_job,
            timeout=55,
            minute=set(range(0, 60, sweep_minutes)) if sweep_minutes < 60 else None,
            run_at_startup=True,
        ),
        cron(
            relay_notifications_job,
            timeout=55,
            minute=set(range(0, 60, relay_minutes)) if relay_minutes < 60 else None,
            run_at_startup=True,
        ),
        # On-chain XP payments: check open payment requests every minute.
        cron(onchain_payment_sweep, minute=set(range(60)), run_at_startup=True, timeout=55),
        cron(payment_request_sweep, minute=set(range(60)), run_at_startup=True, timeout=55),
        cron(stale_task_watchdog, minute=set(range(60)), run_at_startup=True, timeout=55),
        cron(wallet_alert_sweep, minute=set(range(60)), run_at_startup=True, timeout=55),
        # Retention sweep (phase 10): privacy windows, daily at 03:17 UTC.
        cron(run_retention_sweep_job, minute=17, hour=3, run_at_startup=False),
    )


def _redis_settings():
    """Point arq at XP_REDIS_URL (arq otherwise assumes localhost:6379)."""
    from arq.connections import RedisSettings

    url = get_settings().redis_url
    return RedisSettings.from_dsn(url) if url else RedisSettings()


class WorkerSettings:
    """arq configuration; functions are the allowlisted job surface."""

    functions = (
        generate_pdf_report,
        generate_receipt_pdf,
        run_agent_task_job,
        run_scheduled_jobs_job,
        relay_notifications_job,
        run_retention_sweep_job,
    )
    redis_settings = _redis_settings()
    cron_jobs = _build_cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = get_settings().agent_task_timeout_seconds  # bounded execution
    keep_result = 3600
    health_check_interval = 30


AI_QUEUE = "satish:ai"


AI_ALIVE_KEY = f"{AI_QUEUE}:alive"
AI_ALIVE_TTL = 180  # seconds; refreshed every minute, so it never lapses while the worker runs


async def _mark_ai_alive(ctx: dict[str, Any]) -> None:
    """Our own heartbeat for the app's "is Satish AI online?" check.
    (arq's built-in one expires between its writes.)"""
    import time

    redis = ctx.get("redis")
    if redis is not None:
        await redis.set(AI_ALIVE_KEY, str(int(time.time())), ex=AI_ALIVE_TTL)


async def ai_startup(ctx: dict[str, Any]) -> None:
    await startup(ctx)
    await _mark_ai_alive(ctx)


async def ai_heartbeat_and_watchdog(ctx: dict[str, Any]) -> dict[str, Any]:
    await _mark_ai_alive(ctx)
    return await stale_task_watchdog(ctx)


def _build_ai_cron_jobs() -> tuple:
    from arq.cron import cron

    return (cron(ai_heartbeat_and_watchdog, minute=set(range(60)), run_at_startup=True, timeout=55),)


class AIWorkerSettings:
    """Dedicated worker for Satish AI tasks (its own queue and slots), so a
    task never waits behind the minute-by-minute payment/alert sweeps."""

    functions = (run_agent_task_job, generate_pdf_report)
    queue_name = AI_QUEUE
    redis_settings = _redis_settings()
    cron_jobs = _build_ai_cron_jobs()
    on_startup = ai_startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = get_settings().agent_task_timeout_seconds
    keep_result = 3600
    health_check_interval = 20
