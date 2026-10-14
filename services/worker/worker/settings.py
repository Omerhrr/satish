"""arq WorkerSettings — run with: arq worker.settings.WorkerSettings"""

from __future__ import annotations

from typing import Any

from xp_core.config import get_settings
from xp_core.logging import setup_logging

from worker.jobs.pdf import generate_pdf_report


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    ctx["settings"] = settings


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


class WorkerSettings:
    """arq configuration; functions are the allowlisted job surface."""

    functions = (generate_pdf_report,)
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 300  # bounded execution (dsh_integration requirements)
    keep_result = 3600
    health_check_interval = 30
