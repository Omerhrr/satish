# Security Policy

## Reporting a vulnerability

Email the maintainers (see the repository owner's profile for the current
contact) or open a GitHub security advisory. Do **not** open a public
issue for anything you believe is exploitable.

Include: affected surface (endpoint/module), reproduction steps or a
proof-of-concept, and the commit you tested against. Regtest/canned-mode
findings are welcome — the deterministic twin is designed to make
settlement bugs reproducible without mainnet funds.

## Scope

In scope: everything in this repository — the FastAPI surface, the XP
ledger and settlement path, wallet/Lightning adapters, the DSH agent wall
(scopes, approvals, tool registry, untrusted-content handling), the
credential vault, the Mini App, and the operational tooling
(rate limiting, alerts, retention).

Out of scope: Telegram platform issues, GitHub infrastructure, upstream
vulnerabilities in lnd/BDK/DeepSeek (report upstream; we track advisories
via `make audit` and dependency review).

## Our commitments

- **90-day disclosure window** from report to public disclosure,
  coordinated with the reporter; earlier if actively exploited.
- No legal action against good-faith research that respects user data and
  never touches funds that are not yours (regtest/canned only).
- Findings land in `docs/security-review.md`'s findings register with
  severity, fix, and test; systemic gaps also enter
  `docs/known-limitations.md` until closed.

## What we will honestly say today

- This build has **not** had an independent external security review yet
  (KL-15) — that is a release gate for real-value production use.
- `/ops/*` endpoints are DEV_MODE-gated only (KL-11); do not deploy to
  shared environments before an operator identity layer exists.
- The rate limiter is per-process in-memory (KL-09); multi-worker
  deployments need the Redis backend first.
- No mainnet anywhere: providers refuse mainnet at construction by design.
