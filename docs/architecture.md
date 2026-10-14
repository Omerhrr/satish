# Architecture

## Logical components (plan: architecture.logical_components)

```
┌────────────────┐      ┌──────────────────────────────┐
│  Telegram Bot  │──────▶  Mini App (Nuxt, apps/web)   │
│  (apps/bot)    │ cmds │ wallet · XP · tasks · security│
└───────┬────────┘      └──────────────┬───────────────┘
        │ Bot API                      │ REST /api/v1 (Bearer session)
        │                              ▼
        │               ┌──────────────────────────────┐
        │               │   FastAPI (services/api)     │
        │               │ auth · XP ledger · tasks ·   │
        │               │ artifacts · approvals · audit│
        │               └───┬──────────┬───────────┬───┘
        │                   │          │           │
        │        ┌──────────▼───┐  ┌───▼──────┐  ┌─▼──────────────┐
        └───────▶│  Worker      │  │ Postgres │  │ Agent adapter  │
          notify │ (arq+WeasyP) │  │ (16 tbl) │  │ (DSH/DeepSeek) │
                 └──────┬───────┘  └──────────┘  └───┬────────────┘
                        │                            │ typed allowlisted tools
                 ┌──────▼───────┐           ┌────────▼─────────┐
                 │ Object store │           │ wallet-adapter / │
                 │ (private)    │           │ lightning-adapter│
                 └──────────────┘           └──────────────────┘
```

## Trust boundaries (plan: architecture.trust_boundaries)

1. **Telegram ↔ platform** — initData validated server-side (HMAC-SHA256,
   freshness-bounded); chat is untrusted transport and never carries keys.
2. **Agent ↔ platform** — the adapter is the only model surface; tools are
   allowlisted, typed, scoped, budgeted, and approval-gated. Model output is
   data, never authorization.
3. **Application ↔ signing** — signing happens only through the
   `SigningBoundary`; the agent has no representation there at all.
4. **Worker ↔ storage** — artifacts are private by default; delivery is via
   authorized API routes with ownership checks.
5. **User ↔ funds** — self-custody: key material exists (in phase 3) only in
   the user's chosen signer; the server stores metadata exclusively.

## Data model

16 tables (plan: data_model.tables), migrated via Alembic revision
`414fb4b2ccf0_initial_schema_16_tables`:

users, telegram_accounts, sessions, wallets, wallet_addresses,
wallet_transactions, payment_intents, xp_accounts, xp_ledger_entries, tasks,
task_steps, approvals, connected_services, artifacts, scheduled_jobs,
audit_events.

Key invariants encoded at DB/service level:

- `xp_accounts.balance >= 0` (CHECK) and CAS-style updates: concurrent tasks
  cannot spend the same credits.
- `xp_ledger_entries.idempotency_key` UNIQUE: every transition replays safely;
  a payment credits exactly once.
- Ledger is append-only; balance == SUM(entries) is continuously tested.
- `wallets` has no secret columns — metadata only.

## XP economy (plan: xp_economy)

- XP is an internal usage credit — not Bitcoin, not a token, not a claim on funds.
- Purchase: payment intent → verified settlement → single idempotent credit.
- Task: estimate → approve budget → atomic reservation → metered execution →
  charge within cap → release unused → transparent receipt.
- Published conversion rate lives in settings (`XP_SATS_PER_XP`) and is
  exposed at `GET /api/v1/xp/rate`.

## API surface (/api/v1)

Implemented now: health/capabilities, auth (telegram exchange, me),
xp (rate, balance, ledger, dev grant), tasks (create/list/get/cancel with
reservation), artifacts (demo-pdf pipeline, list, get, authorized download).

Shaped for later phases: wallets, addresses, lightning, automations — each
lands behind its adapter/integration spike with honest 409/501-style
capability reporting rather than fake success.

## Deviation note

`packages/py-core` is a shared Python package (settings/models/ledger) beyond
the plan's TS-only `packages/` — it avoids duplicating models and ledger
logic across api/worker and keeps the packaging question (single repo,
workspace tooling) aligned with the plan's "integration spike" guidance.
