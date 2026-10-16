"""Retention sweep job (phase 10: privacy and retention policy enforcement).

Worker cron wrapper around xp_core.jobs.retention.retention_sweep. Runs
daily; deletes only within the configured windows and never touches the
money trail or audit surfaces (see the module docstring there).
"""

from __future__ import annotations

from typing import Any

from xp_core.config import get_settings
from xp_core.logging import get_logger, setup_logging

log = get_logger(__name__)


async def run_retention_sweep_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """arq job: apply the privacy/retention windows (phase 10)."""
    setup_logging(get_settings().log_level)
    from xp_core.db import get_session_factory
    from xp_core.jobs.retention import retention_sweep

    factory = get_session_factory()
    async with factory() as session:
        return await retention_sweep(session)
