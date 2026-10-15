"""Automation sweep job (phase 9).

The worker's cron heartbeat for scheduled jobs: every sweep, due jobs get
ONE scheduling decision each via xp_core.services.automation (budget caps,
run history, failure policy, approval-wait). The executor is the same
durable agent runner used by the API path, so resume-after-approval works
identically from either surface.
"""

from __future__ import annotations

from typing import Any

from xp_core.config import get_settings
from xp_core.logging import get_logger, setup_logging

log = get_logger(__name__)


async def _execute_task(session_factory, task_id: str, settings, resume: bool = False):
    from app.services.agent_service import run_agent_task

    return await run_agent_task(session_factory, task_id, settings, resume=resume)


async def run_scheduled_jobs_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq job: execute all due scheduled jobs (one decision per job)."""
    setup_logging(get_settings().log_level)
    from xp_core.db import get_session_factory
    from xp_core.services.automation import run_due_jobs

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        outcomes = await run_due_jobs(
            session,
            settings,
            session_factory=factory,
            execute_task=_execute_task,
        )
    if outcomes:
        log.info("automation_sweep_complete", outcomes=outcomes)
    return {"executed": len(outcomes), "outcomes": outcomes}
