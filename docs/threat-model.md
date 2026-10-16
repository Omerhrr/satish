# Threat Model (working notes — phase 0 deliverable)

Scope: phase 1 scaffold. This document tracks assets, adversaries, and
mitigations that the implementation already honors, plus open items the
release gates require before testnet/mainnet.

## Assets

| Asset | Where it lives today |
|---|---|
| Seed phrases / private keys | NOWHERE — not in DB, logs, agent context, or chat (phase 3 keeps them in the user's signer) |
| XP balances & ledger | Postgres/SQLite, append-only entries + CAS balance updates |
| Payment state | `payment_intents` with idempotency keys; settlement verified before credit |
| Session tokens | Only SHA-256 hashes stored; bearer expiry checked |
| Generated artifacts | Private storage; authorized, ownership-checked delivery |
| Audit trail | `audit_events` — redacted metadata, request-correlated |

## Adversaries & mitigations

**Forged Mini App identity** — server-side HMAC validation of initData with
freshness window (`verify_telegram_init_data`); unit-tested against tampered
payloads, wrong tokens, stale auth dates. Open: replay window tuning and
session binding in phase 2.

**Prompt-injected agent** — all retrieved content wrapped as untrusted data;
model output never grants authorization; tool registry enforces scopes,
required arguments, budgets, timeouts; sensitive tools require digest-bound
user approval. Open: per-tool output size caps and rate limiting before
research tools ship.

**Ledger manipulation** — append-only entries, unique idempotency keys,
CHECK(balance >= 0), atomic CAS reservations; no client-supplied balance is
ever authoritative (api_rules). Refunds/adjustments append new entries and
write audit events.

**Artifact leakage** — private-by-default storage, ownership checks on every
access route; keys are path-normalized against traversal. Open: expiring
signed URLs when S3-compatible storage lands.

**Secret leakage into logs** — structlog payloads carry IDs only; no seed,
private key, or full payment credential fields exist in the models at all
(structural prevention, not just convention).

**Dependency/supply chain** — pinned revisions in pyproject/bun.lock; CI runs
lint+tests on every PR. Open: dependency review + license review (phase 0
deliverables), DSH upstream revision pinning.

## Release gate reminders (plan: wallet_and_security.release_gates)

- Regtest pass of create/receive/send/restore before any testnet demo.
- Signing UI shows destination, amount, fee, network before authorization.
- Address aliases can never silently change a destination.
- Failed/uncertain broadcasts represented accurately.
- Lightning: channel-state backup + recovery documented before public beta;
  never claim a seed phrase alone restores channels.
- No mainnet until every gate above passes independent review.

## Phase-10 threat-model review (2026-10-16)

A structured re-review of every trust boundary after phases 7-9 added
research fetching, commerce scoring, external connections, email sending,
and an automation scheduler. Each new surface was reviewed against the
original STRIDE-per-boundary table; verdicts and deltas below. This review
is INTERNAL — see docs/security-review.md for the honest status of
independent review.

### New surfaces reviewed

| Surface | Threats considered | Verdict / delta |
| --- | --- | --- |
| Research fetch (phase 7) | SSRF via redirects, private-IP probing, oversized responses, non-HTML smuggling | Existing FetchPolicy wall re-verified: scheme allowlist, port 80/443 only, per-hop + per-resolved-IP checks, size/content-type caps. No change. |
| Commerce scoring (phase 8) | Manipulated verdicts via operator weights; untrusted listings presented as facts | Weights are operator-config and echoed in every verdict; defects fall back WITH disclosure; listing prices are typed estimates everywhere. No change. |
| Credential vault (phase 9) | Vault key disclosure, decryption-path proliferation | Single decryption path re-verified; revocation hard-deletes; dev fallback key is disclosed on every response and refused outside dev. No change. |
| Email send (phase 9) | Auto-retry fabricating delivery; resend of sent drafts; approval bypass | Outcome taxonomy (sent/refused/unknown) is final; sent drafts are terminal; send executes only post-approval with matching content digest. No change. |
| Automation scheduler (phase 9) | Budget overrun, failure loops, crash-recovery double-run | Per-run cap enforced by the ledger itself; consecutive-failure ladder auto-pauses; stale-run recovery marks rather than repeats. No change. |
| **API abuse (NEW, phase 10)** | Credential stuffing, scraping, cost-forcing via agent/money endpoints | **Mitigated**: token-bucket rate limiting per route class (auth 10/min, money 60/min, agent 30/min, reads 300/min) with 429 + Retry-After; subject = client IP + bearer fingerprint (no DB hit). In-memory buckets are per-process: multi-worker production must move to the Redis backend (KL-09). Monitoring surfaces deliberately unlimited. |
| **Payment integrity ops (NEW)** | Silent drift between balance row and ledger; double-credited settlements discovered late | **Mitigated**: every reconciliation discrepancy now opens a persisted, deduplicated ReconciliationAlert (critical kinds never auto-resolve); operators ack/resolve via /ops with an audit trail. |
| **Data retention (NEW)** | Indefinite PII/session/draft accumulation (privacy breach blast radius) | **Mitigated**: retention sweep deletes expired sessions, read/unread notifications past windows, finished automation runs, terminal email drafts. Ledger, task_events, audit_events, artifacts are structurally never swept (money + evidence trails). |
| **Restore integrity (NEW)** | Backup that cannot actually restore; silent corruption | **Mitigated**: `make backup-drill` proves a full logical roundtrip with ledger re-reconciliation, 1:1 settlement check, and artifact digest verification on the restored copy. |

### Residual risks accepted for phase 10 (tracked in docs/known-limitations.md)

- Rate limiting is per-process in-memory; a multi-worker deployment without
  the Redis backend under-limits by a factor of worker count (KL-09).
- The subject fingerprint uses the presented (unvalidated) bearer; a client
  rotating fake bearers gets fresh buckets at the same cost as IP rotation
  behind proxies (KL-09).
- The backup drill exercises the logical roundtrip on SQLite; Postgres
  pg_dump/pg_restore + SCB recovery need a live operator host (KL-04/KL-05).
