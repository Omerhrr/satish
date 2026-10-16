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
            minute=set(range(0, 60, sweep_minutes)) if sweep_minutes < 60 else None,
            run_at_startup=True,
        ),
        cron(
            relay_notifications_job,
            minute=set(range(0, 60, relay_minutes)) if relay_minutes < 60 else None,
            run_at_startup=True,
        ),
        # Retention sweep (phase 10): privacy windows, daily at 03:17 UTC.
        cron(run_retention_sweep_job, minute=17, hour=3, run_at_startup=False),
    )


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
    cron_jobs = _build_cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 300  # bounded execution (dsh_integration requirements)
    keep_result = 3600
    health_check_interval = 30
