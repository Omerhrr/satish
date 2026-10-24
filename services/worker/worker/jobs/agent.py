"""Agent task execution job (phase 6).

The durable unit of agent work: runs PlanRunner against the application DB
with DB-backed persistence hooks. Arq job surface; inline-executed by the
dev bridge when no Redis is configured.
"""

from __future__ import annotations

from typing import Any

from xp_core.config import get_settings
from xp_core.logging import get_logger, setup_logging

log = get_logger(__name__)


async def run_agent_task_job(
    ctx: dict[str, Any], *, task_id: str, resume: bool = False
) -> dict[str, Any]:
    """Arq job: execute one agent task with durable state.

    ``resume`` skips steps the DB already recorded as completed (approval
    resume / restart recovery).
    """
    setup_logging(get_settings().log_level)
    from app.services.agent_service import TaskNotRunnable, run_agent_task
    from xp_core.db import get_session_factory

    settings = get_settings()
    try:
        return await run_agent_task(get_session_factory(), task_id, settings, resume=resume)
    except TaskNotRunnable as exc:
        # Already finished elsewhere (e.g. the API ran it while this worker was down).
        log.info("agent_task_skipped", task_id=task_id, reason=str(exc))
        return {"task_id": task_id, "status": "skipped", "reason": str(exc)}
