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
