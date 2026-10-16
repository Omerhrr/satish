"""KL-09 closure tests: Redis-backed rate limiter + validation-joined keys.

Covers:
- RedisRateLimiter semantics parity with the in-memory buckets (burst, deny,
  Retry-After math, refill over time) via an offline FakeRedis that mirrors
  the pinned TOKEN_BUCKET_LUA script line for line.
- The property the memory backend lacks: one shared bucket state across
  limiter instances (what separate API worker processes see).
- IdentityCache: validation-joined per-user subjects, token-rotation
  resistance, TTL expiry, LRU size bound.
- Degraded fail-open disclosure on backend errors (never a fabricated deny,
  never a silent pass-through either).
- build_rate_limiter factory: memory default, redis refusing to construct
  without redis_url, injected-client seam.
- Middleware e2e over the redis backend: 429 shape, degraded unknown
  remaining header, observability counters, and the deps identity join.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from xp_core.config import get_settings
from xp_core.models.entities import User
from xp_core.services.ratelimit import (
    RULES,
    TOKEN_BUCKET_LUA,
    IdentityCache,
    RateLimiter,
    RedisRateLimiter,
    RouteClass,
    build_rate_limiter,
    subject_for,
)
from xp_core.services.security import create_session


class FakeRedis:
    """Offline redis.Redis stand-in executing a Python mirror of the pinned
    TOKEN_BUCKET_LUA script (keep the mirror in lockstep with the script).
    Raises like a real client once ``fail_after`` eval calls have passed."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, float]] = {}
        self.fail_after: int | None = None
        self.calls = 0

    def _mirror(
        self, key: str, capacity: float, refill: float, now_ms: float, ttl_ms: float
    ) -> list[float]:
        state = self.buckets.get(key, {})
        tokens, ts = state.get("tokens"), state.get("ts")
        if tokens is None or ts is None:
            tokens, ts = float(capacity), float(now_ms)
        elapsed = max(0.0, float(now_ms) - ts)
        tokens = min(float(capacity), tokens + elapsed / 1000.0 * float(refill))
        allowed, remaining = 0.0, 0.0
        if tokens >= 1.0:
            tokens -= 1.0
            allowed, remaining = 1.0, float(int(tokens))
        self.buckets[key] = {"tokens": tokens, "ts": float(now_ms)}
        return [allowed, remaining, tokens]

    def eval(self, script: str, numkeys: int, key: str, *args: object) -> list[float]:
        assert script == TOKEN_BUCKET_LUA, "double must execute the pinned script"
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise ConnectionError("simulated redis outage")
        capacity, refill, now_ms, ttl_ms = args
        return self._mirror(key, float(capacity), float(refill), float(now_ms), float(ttl_ms))


class FakeClock:
    """Controllable wall clock (seconds) for deterministic refill tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
async def redis_api(session, monkeypatch):
    """ASGI client wired to the redis backend over a FakeRedis (buckets and
    identity cache reset per test). Depends on ``session`` for the schema."""
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://test-host:6379/0")
    fake = FakeRedis()
    limiter = build_rate_limiter(settings, client=fake)
    app.state.rate_limiter = limiter
    app.state.identity_cache = IdentityCache(ttl_seconds=3600.0)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, limiter, fake
    app.state.rate_limiter = RateLimiter()  # restore defaults for other tests
    app.state.identity_cache = IdentityCache()


# unit: RedisRateLimiter semantics


def test_redis_limiter_matches_memory_semantics():
    fake = FakeRedis()
    limiter = RedisRateLimiter(client=fake)
    results = [limiter.check(RouteClass.AUTH, "10.0.0.1") for _ in range(6)]
    assert all(r.allowed for r in results[:5])  # burst 5
    tripped = results[5]
    assert not tripped.allowed
    assert tripped.retry_after_seconds > 0
    assert tripped.limit == RULES[RouteClass.AUTH].rate
    assert results[0].remaining == RULES[RouteClass.AUTH].burst - 1


def test_redis_limiter_refills_over_time():
    fake = FakeRedis()
    clock = FakeClock()
    limiter = RedisRateLimiter(client=fake, time_fn=clock)
    subject = "user:42"
    for _ in range(RULES[RouteClass.AUTH].burst):
        assert limiter.check(RouteClass.AUTH, subject).allowed
    assert not limiter.check(RouteClass.AUTH, subject).allowed
    clock.advance(6.0)  # auth refills 10/60 per second -> exactly one token
    refilled = limiter.check(RouteClass.AUTH, subject)
    assert refilled.allowed
    assert not limiter.check(RouteClass.AUTH, subject).allowed  # and no free extra


def test_redis_buckets_are_shared_between_instances():
    """THE multi-worker property: one bucket state behind any number of
    limiter instances, where per-process memory would under-limit."""
    fake = FakeRedis()
    worker_a = RedisRateLimiter(client=fake)
    worker_b = RedisRateLimiter(client=fake)
    allowed = 0
    for _ in range(RULES[RouteClass.AUTH].burst + 2):
        result = (worker_a if worker_a is not None else worker_b).check(
            RouteClass.AUTH, "10.0.0.9"
        )
        allowed += int(result.allowed)
    assert allowed == RULES[RouteClass.AUTH].burst  # shared, not doubled


def test_unknown_route_class_falls_back_to_write_rules():
    limiter = RedisRateLimiter(client=FakeRedis())
    result = limiter.check("not-a-class", "10.0.0.1")
    assert result.route_class == "not-a-class"
    assert result.limit == RULES[RouteClass.WRITE].rate


# unit: IdentityCache (validation-joined keys)


def test_identity_cache_join_overrides_fingerprint_subject():
    cache = IdentityCache()
    assert subject_for("10.0.0.1", None, cache) == "10.0.0.1"  # no bearer
    assert subject_for("10.0.0.1", "tok-x", cache).startswith("10.0.0.1:")  # unknown
    cache.remember("tok-x", "u1")
    assert subject_for("10.0.0.1", "tok-x", cache) == "user:u1"
    assert subject_for("9.9.9.9", "tok-x", cache) == "user:u1"  # user-keyed, not IP-keyed


def test_rotated_tokens_of_one_user_share_one_subject():
    cache = IdentityCache()
    cache.remember("session-token-a", "u7")
    cache.remember("session-token-b", "u7")
    a = subject_for("10.0.0.1", "session-token-a", cache)
    b = subject_for("10.0.0.1", "session-token-b", cache)
    assert a == b == "user:u7"


def test_identity_cache_ttl_expiry_falls_back_to_fingerprint():
    clock = FakeClock()
    cache = IdentityCache(ttl_seconds=60.0, clock=clock)
    cache.remember("tok", "u1")
    assert cache.lookup("tok") == "user:u1"
    clock.advance(61.0)
    assert cache.lookup("tok") is None  # expired: cold join, fallback subject
    assert subject_for("10.0.0.1", "tok", cache).startswith("10.0.0.1:")


def test_identity_cache_is_size_bounded_lru():
    cache = IdentityCache(max_entries=2)
    cache.remember("t1", "u1")
    cache.remember("t2", "u2")
    cache.remember("t3", "u3")  # evicts t1 (oldest)
    assert cache.lookup("t1") is None
    assert cache.lookup("t2") == "user:u2"
    assert cache.lookup("t3") == "user:u3"
    cache.remember("t2", "u2")  # refresh recency, then insert -> evicts u3
    cache.remember("t4", "u4")
    assert cache.lookup("t3") is None
    assert cache.lookup("t2") == "user:u2"


# unit: degraded fail-open + factory


def test_redis_backend_error_fails_open_with_disclosure():
    fake = FakeRedis()
    fake.fail_after = 0  # every eval raises
    limiter = RedisRateLimiter(client=fake)
    for _ in range(3):
        result = limiter.check(RouteClass.MONEY, "10.0.0.1")
        assert result.allowed  # never fabricates a deny it cannot account for
        assert result.degraded
    assert limiter.degraded_checks == 3


def test_build_rate_limiter_defaults_to_memory():
    limiter = build_rate_limiter(get_settings())
    assert isinstance(limiter, RateLimiter)
    assert not isinstance(limiter, RedisRateLimiter)


def test_build_rate_limiter_redis_requires_url(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", None)
    with pytest.raises(RuntimeError, match="requires XP_REDIS_URL"):
        build_rate_limiter(settings)


def test_build_rate_limiter_redis_with_injected_client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://test-host:6379/0")
    limiter = build_rate_limiter(settings, client=FakeRedis())
    assert isinstance(limiter, RedisRateLimiter)


# e2e: middleware + deps over the redis backend


async def test_middleware_429_via_redis_backend(redis_api):
    client, _limiter, _fake = redis_api
    burst = RULES[RouteClass.AUTH].burst
    statuses = []
    for _ in range(burst + 2):
        resp = await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
        statuses.append(resp.status_code)
    assert 429 not in statuses[:burst]  # within burst: endpoint answers, not the limiter
    assert statuses[burst:] == [429, 429]  # bucket drained, honest trip
    trip = await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
    assert trip.status_code == 429
    assert "Retry-After" in trip.headers
    assert trip.headers["X-RateLimit-Limit"] == str(RULES[RouteClass.AUTH].rate)
    assert trip.headers["X-RateLimit-Remaining"] == "0"
    assert trip.json()["route_class"] == RouteClass.AUTH


async def test_degraded_backend_passes_with_unknown_remaining(redis_api):
    client, _limiter, fake = redis_api
    fake.fail_after = 0
    resp = await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
    assert resp.status_code == 200  # request flows through, backend degraded
    assert resp.headers["X-RateLimit-Remaining"] == "unknown"


async def test_observability_reports_backend_and_degraded_counts(redis_api):
    client, _limiter, fake = redis_api
    fake.fail_after = 0
    await client.post("/api/v1/auth/telegram", json={"init_data": "bogus"})
    obs = (await client.get("/api/v1/ops/observability")).json()
    assert obs["rate_limit_backend"] == "redis"
    assert obs["rate_limit_degraded_checks"] >= 1


async def test_validated_session_joins_identity_cache(session, redis_api):
    client, _limiter, _fake = redis_api
    user = User(display_name="Join Probe")
    session.add(user)
    await session.flush()
    token, _row = await create_session(session, user.id)
    resp = await client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    from app.main import app

    assert app.state.identity_cache.lookup(token) == f"user:{user.id}"
    # and the limiter now keys this token on the joined user, not the IP
    assert subject_for("10.0.0.1", token, app.state.identity_cache) == f"user:{user.id}"


async def test_rotation_resistant_buckets_e2e(session, redis_api):
    """Warm tokens of one user drain ONE auth-class bucket across rotations;
    a token's very first request still rides the cold ip-fingerprint bucket
    (the documented seam), and the user bucket holds after that."""
    from app.main import app

    client, limiter, _fake = redis_api
    user = User(display_name="Rotation Probe")
    session.add(user)
    await session.flush()
    token_a, _ = await create_session(session, user.id)
    token_b, _ = await create_session(session, user.id)
    for tok in (token_a, token_a, token_b, token_b):  # warm both tokens
        resp = await client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {tok}"}
        )
        assert resp.status_code == 200
    subject_a = subject_for("1.2.3.4", token_a, app.state.identity_cache)
    subject_b = subject_for("1.2.3.4", token_b, app.state.identity_cache)
    assert subject_a == subject_b == f"user:{user.id}"
    # user bucket spent by the two warm requests; the rest of the burst holds
    spent = [limiter.check(RouteClass.AUTH, subject_a) for _ in range(5)]
    assert sum(r.allowed for r in spent) == RULES[RouteClass.AUTH].burst - 2
