"""Async SQLAlchemy engine/session plumbing shared by API and worker."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from xp_core.config import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base for all XP models."""


def new_id() -> str:
    """Portable UUID primary key generator (String(36) columns)."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """UTC timestamps in storage (data_rules #1)."""
    return datetime.now(UTC)


def make_engine(settings: Settings | None = None) -> AsyncEngine:
    s = settings or get_settings()
    if s.is_sqlite:
        return create_async_engine(s.database_url, echo=s.db_echo)
    return create_async_engine(
        s.database_url, echo=s.db_echo, pool_size=10, max_overflow=10, pool_pre_ping=True
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency producing a request-scoped session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """Override in tests to point at a scratch database."""
    global _session_factory
    _session_factory = factory


async def init_db(create_all: bool = True) -> None:
    """Dev/test helper. Production uses Alembic migrations instead."""
    from xp_core.models import entities  # noqa: F401  (register metadata)

    engine = make_engine()
    if create_all:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
