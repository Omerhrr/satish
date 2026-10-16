"""Abuse and rate-limit controls (phase 10, deliverable: Abuse and rate-limit controls).

Design (honest, phase-10 scope):

- Token buckets keyed by ``(route_class, subject)``. The subject is derived
  WITHOUT a database hit: ``client_ip`` when no bearer credential is
  presented, otherwise ``client_ip + fingerprint(bearer)`` so concurrent
  sessions of the same client do not drain one shared bucket. The presented
  bearer is NOT validated here (that is the auth dependency's job) — a forged
  bearer only buys the attacker a fresh bucket, the same power spoofing an IP
  behind a proxy has. A validation-joined per-user limit is the documented
  production upgrade path (see docs/security-review.md KL item).
- Buckets are in-memory per API process. Multi-worker deployments must move
  to the Redis backend (documented upgrade path); the bucket interface is
  backend-agnostic so the swap does not touch call sites.
- Route classes are code-pinned for phase 10 (auth tightest, money paths
  tight, agent task creation medium, reads loose); ``rate_limit_enabled``
  is the operator kill switch.
- Trips log a structured warning with a hashed subject — never the raw
  bearer — and respond 429 with ``Retry-After`` plus honest
  ``X-RateLimit-*`` headers.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

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


def subject_for(client_ip: str, bearer: str | None) -> str:
    """Credential-fingerprinted subject (no DB hit, no raw bearer anywhere)."""
    if not bearer:
        return client_ip
    fingerprint = hashlib.sha256(bearer.encode()).hexdigest()[:12]
    return f"{client_ip}:{fingerprint}"


def log_trip(route_class: str, subject: str, path: str, retry_after: int) -> None:
    # subject may contain an IP; keep it — IPs in ops logs are standard, but
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
    "RateLimitResult",
    "RateLimiter",
    "RouteClass",
    "classify_path",
    "log_trip",
    "subject_for",
]
