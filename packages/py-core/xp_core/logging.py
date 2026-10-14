"""Structured JSON logging with correlation IDs (api_rules: correlation IDs)."""

from __future__ import annotations

import contextvars
import logging
import sys

import structlog

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def add_request_id(
    logger: object, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    event_dict["request_id"] = request_id_var.get()
    return event_dict


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog once per process. Call from every entrypoint."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_request_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
