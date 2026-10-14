"""XP FastAPI application entrypoint.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from xp_core.config import get_settings
from xp_core.logging import request_id_var, setup_logging

from app.api.v1.router import api_router

VERSION = "0.1.0"


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    log = structlog.get_logger("api")

    app = FastAPI(
        title="XP API",
        version=VERSION,
        description=(
            "Bitcoin-native Telegram AI workforce platform. "
            "Telegram is an interface, not a private-key vault; the agent never "
            "receives seed phrases or unrestricted signing authority."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get(settings.request_id_header) or request.headers.get(
            "x-request-id"
        )
        if not rid:
            import uuid

            rid = str(uuid.uuid4())
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers[settings.request_id_header] = rid
        return response

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "xp-api", "version": VERSION, "env": settings.env}

    app.include_router(api_router, prefix="/api/v1")

    @app.on_event("startup")
    async def _startup() -> None:
        log.info(
            "api_starting",
            env=settings.env,
            dev_mode=settings.dev_mode,
            sqlite=settings.is_sqlite,
            redis=bool(settings.redis_url),
        )

    return app


app = create_app()
