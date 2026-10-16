"""Abuse and rate-limit controls (phase 10, deliverable: Abuse and rate-limit controls).

Design (honest, phase-10 scope):

- Token buckets keyed by ``(route_class, subject)``. The subject is derived
  WITHOUT a database hit: ``client_ip`` when no bearer credential is
  presented, otherwise ``client_ip + fingerprint(bearer)`` so concurrent
  sessions of the same client do not drain one shared bucket. The presented
  bearer is NOT validated here (that is the auth dependency's job) - a forged
  bearer only buys the attacker a fresh bucket, the same power spoofing an IP
  behind a proxy has.
- Validation-joined per-user keys (KL-09 closure): the auth dependency feeds
  every successfully validated bearer into the process-local
  ``IdentityCache``; the subject derivation then prefers ``user:<id>`` over
  the credential fingerprint, so rotating session tokens can no longer buy
  a fresh bucket - every valid token of one user drains ONE bucket. A bearer
  never seen valid (forged, expired, first request of a token) falls back to
  the ip:fingerprint subject; the join takes effect from the second request
  of that token onward.
- Backends: ``RateLimiter`` is in-memory per API process (default).
  ``RedisRateLimiter`` holds the same interface over one shared Redis token
  bucket per subject (atomic Lua script), so multi-worker deployments stop
  under-limiting by worker count. Both are built through
  ``build_rate_limiter`` from settings; ``rate_limit_backend=redis`` without
  ``redis_url`` refuses to construct. On a Redis error the limiter fails
  OPEN (never fabricates an enforcement decision) and reports the degraded
  state on the result and through the ops observability surface.
- Route classes are code-pinned for phase 10 (auth tightest, money paths
  tight, agent task creation medium, reads loose); ``rate_limit_enabled``
  is the operator kill switch.
- Trips log a structured warning with a hashed subject - never the raw
  bearer - and respond 429 with ``Retry-After`` plus honest
  ``X-RateLimit-*`` headers.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from xp_core.logging import get_logger

log = get_logger(__name__)


class RouteClass:
    """Path-class constants; limits are pinned per class in RULES."""

    AUTH = "auth"  # initData exchanges, session lifecycle
    MONEY = "money"  # wallets, lightning, xp purchases/grants
    AGENT = "agent"  # task creation / mutation (spends budget)
    READ = "read"  # GET/HEAD reads
    WRITE = "write"  # everything else


@dataclass(frozen=True)
class Rule:
    """``rate`` requests per ``per_seconds`` with bucket ``burst`` capacity."""

    rate: int
    per_seconds: float
    burst: int


RULES: dict[str, Rule] = {
    RouteClass.AUTH: Rule(rate=10, per_seconds=60.0, burst=5),
    RouteClass.MONEY: Rule(rate=60, per_seconds=60.0, burst=20),
    RouteClass.AGENT: Rule(rate=30, per_seconds=60.0, burst=10),
    RouteClass.READ: Rule(rate=300, per_seconds=60.0, burst=100),
    RouteClass.WRITE: Rule(rate=120, per_seconds=60.0, burst=40),
}

SKIP_PREFIXES = ("/healthz", "/api/v1/health", "/api/v1/capabilities")


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    route_class: str
    degraded: bool = False  # backend error: request allowed, enforcement unknown


@dataclass
class RateLimiter:
    """In-memory token buckets; one instance per API process (app.state)."""

    rules: dict[str, Rule] = field(default_factory=lambda: dict(RULES))
    bucket_ttl_seconds: float = 3600.0
    max_buckets: int = 10_000
    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    _last_sweep: float = field(default_factory=time.monotonic)

    def _sweep_if_needed(self, now: float) -> None:
        if len(self._buckets) < self.max_buckets and now - self._last_sweep < 60:
            return
        stale = [
            key
            for key, b in self._buckets.items()
            if now - b.updated_at > self.bucket_ttl_seconds
        ]
        for key in stale:
            del self._buckets[key]
        self._last_sweep = now

    def check(self, route_class: str, subject: str) -> RateLimitResult:
        """Try to take one token; returns an honest result either way."""
        rule = self.rules.get(route_class, self.rules[RouteClass.WRITE])
        now = time.monotonic()
        self._sweep_if_needed(now)
        refill_per_second = rule.rate / rule.per_seconds
        key = (route_class, subject)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(rule.burst), updated_at=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(rule.burst, bucket.tokens + elapsed * refill_per_second)
            bucket.updated_at = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return RateLimitResult(
                allowed=True,
                limit=rule.rate,
                remaining=int(bucket.tokens),
                retry_after_seconds=0,
                route_class=route_class,
            )
        deficit = 1.0 - bucket.tokens
        retry_after = int(deficit / refill_per_second) + 1 if refill_per_second > 0 else 60
        return RateLimitResult(
            allowed=False,
            limit=rule.rate,
            remaining=0,
            retry_after_seconds=retry_after,
            route_class=route_class,
        )


class IdentityCache:
    """Process-local join of validated bearers to user subjects (KL-09).

    The auth dependency calls ``remember(token, user_id)`` on every successful
    validation; subject derivation prefers the joined ``user:<id>`` subject so
    token rotation cannot refresh buckets. Entries expire after ``ttl_seconds``
    (matched to the bucket TTL) and the map is size-bounded; a cold entry means
    the request falls back to the ip:fingerprint subject - a fresh bucket for
    one request, never a permanent bypass.
    """

    def __init__(
        self,
        ttl_seconds: float = 3600.0,
        max_entries: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(bearer: str) -> str:
        return hashlib.sha256(bearer.encode()).hexdigest()[:12]

    def remember(self, bearer: str, user_id: str) -> None:
        entry = (f"user:{user_id}", self.clock())
        with self._lock:
            self._entries[self.fingerprint(bearer)] = entry
            self._entries.move_to_end(self.fingerprint(bearer))
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def lookup(self, bearer: str | None) -> str | None:
        if not bearer:
            return None
        now = self.clock()
        with self._lock:
            entry = self._entries.get(self.fingerprint(bearer))
            if entry is None:
                return None
            subject, seen_at = entry
            if now - seen_at > self.ttl_seconds:
                del self._entries[self.fingerprint(bearer)]
                return None
            self._entries.move_to_end(self.fingerprint(bearer))
            return subject


# Atomic token bucket over one Redis hash. ARGV: capacity, refill_per_second,
# now_ms, ttl_ms. Clock comes from the caller (clamped against negative drift
# so skewed workers can only slow a refill, never move tokens backward).
# The committed FakeRedis test double mirrors THIS script line for line - if
# the script changes, the mirror and its tests must change with it.
TOKEN_BUCKET_LUA = """
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
    tokens = capacity
    ts = now
end
local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed / 1000.0 * refill)
local allowed = 0
local remaining = 0
if tokens >= 1.0 then
    tokens = tokens - 1.0
    allowed = 1
    remaining = math.floor(tokens)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return {allowed, remaining, tokens}
"""


@dataclass
class RedisRateLimiter:
    """Shared token buckets over Redis; one instance per API process.

    Same ``check`` contract as ``RateLimiter``. Any backend error fails OPEN
    with ``degraded=True`` (an abuse limiter must never invent a denial it
    cannot account for, and must not take the API down with it); degraded
    checks are counted and surfaced through /ops/observability.
    """

    client: Any
    rules: dict[str, Rule] = field(default_factory=lambda: dict(RULES))
    bucket_ttl_seconds: float = 3600.0
    time_fn: Callable[[], float] = time.time
    degraded_checks: int = 0
    _last_degraded_log: float = field(default=0.0, repr=False)

    def check(self, route_class: str, subject: str) -> RateLimitResult:
        rule = self.rules.get(route_class, self.rules[RouteClass.WRITE])
        refill_per_second = rule.rate / rule.per_seconds
        key = f"rl:{route_class}:{subject}"
        now_ms = int(self.time_fn() * 1000)
        ttl_ms = max(1, int(self.bucket_ttl_seconds * 1000))
        try:
            raw = self.client.eval(
                TOKEN_BUCKET_LUA,
                1,
                key,
                rule.burst,
                refill_per_second,
                now_ms,
                ttl_ms,
            )
        except Exception as exc:
            self.degraded_checks += 1
            now = self.time_fn()
            if now - self._last_degraded_log >= 10.0:
                self._last_degraded_log = now
                log.warning(
                    "rate_limit_backend_degraded",
                    backend="redis",
                    error=type(exc).__name__,
                    mode="fail_open",
                )
            return RateLimitResult(
                allowed=True,
                limit=rule.rate,
                remaining=0,
                retry_after_seconds=0,
                route_class=route_class,
                degraded=True,
            )
        allowed, remaining = int(raw[0]), int(raw[1])
        tokens = float(raw[2])
        if allowed:
            return RateLimitResult(
                allowed=True,
                limit=rule.rate,
                remaining=remaining,
                retry_after_seconds=0,
                route_class=route_class,
            )
        retry_after = (
            int((1.0 - tokens) / refill_per_second) + 1 if refill_per_second > 0 else 60
        )
        return RateLimitResult(
            allowed=False,
            limit=rule.rate,
            remaining=0,
            retry_after_seconds=retry_after,
            route_class=route_class,
        )


def build_rate_limiter(settings: Any, client: Any = None) -> RateLimiter | RedisRateLimiter:
    """Construct the configured backend; refuses misconfiguration loudly.

    ``client`` is the test seam (a redis-like object); production leaves it
    None and a client is built from ``settings.redis_url``. ``backend=redis``
    without a URL refuses to construct so a requested shared backend is never
    silently downgraded to per-process memory.
    """
    backend = getattr(settings, "rate_limit_backend", "memory")
    if backend == "redis":
        if not settings.redis_url:
            raise RuntimeError(
                "XP_RATE_LIMIT_BACKEND=redis requires XP_REDIS_URL; "
                "refusing to silently fall back to per-process memory buckets"
            )
        if client is None:
            try:
                import redis  # lazy: py-core does not hard-depend on it
            except ImportError as exc:  # pragma: no cover - environment seam
                raise RuntimeError(
                    "XP_RATE_LIMIT_BACKEND=redis needs the redis package "
                    "(pip install redis), which is not installed"
                ) from exc
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        return RedisRateLimiter(
            client=client,
            bucket_ttl_seconds=float(settings.rate_limit_bucket_ttl_seconds),
        )
    return RateLimiter(
        bucket_ttl_seconds=settings.rate_limit_bucket_ttl_seconds,
        max_buckets=settings.rate_limit_max_buckets,
    )


def classify_path(method: str, path: str) -> str:
    """Map (method, path) to a route class. Keep this boring and testable."""
    if path.startswith(SKIP_PREFIXES):
        return ""  # unlimited: monitoring surfaces must not be throttleable
    if path.startswith("/api/v1/auth"):
        return RouteClass.AUTH
    if path.startswith(("/api/v1/wallets", "/api/v1/lightning")):
        return RouteClass.MONEY
    if path.startswith("/api/v1/xp") and method != "GET":
        return RouteClass.MONEY
    if path.startswith("/api/v1/tasks") and method not in ("GET", "HEAD", "OPTIONS"):
        return RouteClass.AGENT
    if method in ("GET", "HEAD", "OPTIONS"):
        return RouteClass.READ
    return RouteClass.WRITE


def subject_for(client_ip: str, bearer: str | None, identity_cache: IdentityCache | None = None) -> str:
    """Subject for a bucket key: joined user when the bearer is known-valid,
    otherwise credential-fingerprinted (no DB hit, no raw bearer anywhere)."""
    if not bearer:
        return client_ip
    if identity_cache is not None:
        joined = identity_cache.lookup(bearer)
        if joined:
            return joined
    fingerprint = hashlib.sha256(bearer.encode()).hexdigest()[:12]
    return f"{client_ip}:{fingerprint}"


def log_trip(route_class: str, subject: str, path: str, retry_after: int) -> None:
    # subject may contain an IP; keep it - IPs in ops logs are standard, but
    # never log the raw bearer.
    log.warning(
        "rate_limit_tripped",
        route_class=route_class,
        subject=subject,
        path=path,
        retry_after_seconds=retry_after,
    )


__all__ = [
    "RULES",
    "SKIP_PREFIXES",
    "TOKEN_BUCKET_LUA",
    "IdentityCache",
    "RateLimitResult",
    "RateLimiter",
    "RedisRateLimiter",
    "RouteClass",
    "build_rate_limiter",
    "classify_path",
    "log_trip",
    "subject_for",
]
