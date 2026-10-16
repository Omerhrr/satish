"""Shared fixtures: fresh SQLite database per test + dev user."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Force deterministic test settings before any xp_core import.
os.environ.setdefault("XP_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("XP_DEV_MODE", "true")
os.environ.setdefault("XP_ARTIFACT_DIR", "./data/test-artifacts")
# Rate-limit buckets live on the shared app singleton; disabled by default so
# one test's requests cannot drain another's budget. test_phase10_ops.py
# enables the limiter explicitly around its own cases.
os.environ.setdefault("XP_RATE_LIMIT_ENABLED", "false")

from xp_core.config import get_settings
from xp_core.db import Base, set_session_factory
from xp_core.services.security import get_or_create_dev_user


@pytest.fixture()
def db_factory():
    """Factory creating isolated in-memory DB sessions.

    Engines are intentionally not disposed here: teardown happens after the
    event loop closes (sync fixture), and in-memory SQLite state dies with
    the test process anyway.
    """

    def _make():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        return engine, factory

    yield _make


@pytest_asyncio.fixture()
async def session(db_factory):
    """Session over a created schema, wired into the global factory."""
    engine, factory = db_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_session_factory(factory)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture()
async def dev_user(session):
    return await get_or_create_dev_user(session)


@pytest.fixture(scope="session")
def settings():
    return get_settings()
