"""XP FastAPI application entrypoint.

Run: uvicorn app.main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from xp_core.config import get_settings
from xp_core.logging import request_id_var, setup_logging
from xp_core.services.ratelimit import (
    IdentityCache,
    build_rate_limiter,
    classify_path,
    log_trip,
    subject_for,
)

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

    # abuse controls (phase 10, backend configurable since KL-09 closure):
    # token buckets per route class; redis shares them across workers.
    # Middleware reads app.state (not this closure) so the backend instance
    # stays swappable in one place.
    app.state.rate_limiter = build_rate_limiter(settings)
    app.state.identity_cache = IdentityCache(
        ttl_seconds=settings.rate_limit_bucket_ttl_seconds
    )

    @app.middleware("http")
    async def rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)
        route_class = classify_path(request.method, request.url.path)
        if not route_class:
            return await call_next(request)  # monitoring surfaces, unlimited
        bearer = request.headers.get("authorization", "")
        bearer = bearer[7:] if bearer.lower().startswith("bearer ") else None
        client_ip = request.client.host if request.client else "unknown"
        subject = subject_for(client_ip, bearer, request.app.state.identity_cache)
        result = request.app.state.rate_limiter.check(route_class, subject)
        if not result.allowed:
            log_trip(route_class, subject, request.url.path, result.retry_after_seconds)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "rate limit exceeded for this surface; retry later",
                    "route_class": result.route_class,
                },
                headers={
                    "Retry-After": str(result.retry_after_seconds),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        # A degraded backend cannot honestly report a remaining count.
        response.headers["X-RateLimit-Remaining"] = (
            "unknown" if result.degraded else str(result.remaining)
        )
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
            rate_limit_backend=settings.rate_limit_backend,
        )

    return app


app = create_app()
