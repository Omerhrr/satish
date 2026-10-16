# XP — Bitcoin-Native Telegram AI Workforce

Open-source, Telegram-native Bitcoin self-custody wallet and AI work platform.
Users pay for research, business intelligence, document creation, and approved
automations using sats converted into application usage credits called **XP**.

> **Status (2026-10-16): phases 0–11 implemented** — 266 tests green, ruff
> clean, every deliverable traced to the plan. Honest boundaries are
> first-class: `docs/known-limitations.md` (KL-01…KL-15) lists exactly what
> is *not* production-proven yet. Nothing here asks you to trust us with
> custody of your funds — see the security model below.

## The one-minute demo (zero external services)

```bash
cd xp && make demo
```

Walks the real API surface on a fresh in-memory database: health → Telegram
session → XP economy → self-custody wallet (seed shown once, never stored) →
Lightning-pack purchase → settlement with **structural double-credit
refusal** → budgeted agent task → WeasyPrint PDF artifact → ops queue.
Canned providers label themselves everywhere; the real-Bitcoin proofs are
the committed drills (`make wallet-regtest`, `make lightning-drill`). Full
transcript: `docs/demo-walkthrough.md`.

## Architecture

```
                      Telegram (interface, never a key vault)
                     ┌────────────┬──────────────────────┐
                     │  Bot       │  Mini App (Nuxt 4)   │
                     │  aiogram 3 │  8 screens           │
                     └─────┬──────┴──────────┬───────────┘
                           │  deep links     │ initData HMAC → 24h sessions
                           ▼                 ▼
              ┌───────────────────────────────────────────┐
              │              FastAPI  (services/api)      │
              │  auth · xp · tasks · artifacts · wallets  │
              │  lightning · connections · drafts         │
              │  automation · notifications · ops         │
              │  rate-limit wall · correlation IDs        │
              └──┬──────────┬──────────┬──────────┬───────┘
                 │          │          │          │
        ┌────────▼───┐ ┌────▼─────┐ ┌──▼───────┐ ┌▼──────────────┐
        │ DSH agent  │ │ wallet   │ │ lightning│ │ email/commerce│
        │ adapter    │ │ adapter  │ │ adapter  │ │ /research     │
        │ pinned rev │ │ BDK      │ │ lnd gRPC │ │ adapters      │
        │ tool wall  │ │ pub-desc │ │ canned/  │ │ SSRF wall,    │
        │ approvals  │ │ only     │ │ real     │ │ vault, SMTP   │
        └────────┬───┘ └────┬─────┘ └──┬───────┘ └───────┬───────┘
                 │          │          │                 │
        ┌────────▼──────────▼──────────▼─────────────────▼───────┐
        │        xp_core (packages/py-core) — the invariants     │
        │  append-only XP ledger · CAS balances · idempotent     │
        │  settlement · reconciliation alerts · retention sweep  │
        └────────────────────────┬───────────────────────────────┘
                                 │
              ┌──────────────────▼───────────────────┐
              │ PostgreSQL (prod) / SQLite (dev)     │
              │ Redis + arq worker (PDF, agent, cron)│
              └──────────────────────────────────────┘
```

Trust boundaries in prose: `docs/architecture.md`; the full STRIDE review:
`docs/threat-model.md`.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Nuxt 4 + Vue + TypeScript (`apps/web`, Telegram Mini App) |
| Backend | FastAPI + Python 3.12 (`services/api`) |
| Agent runtime | DeepSeek via pinned-revision DSH adapter (`services/agent-adapter`) |
| Database | PostgreSQL 16 (prod) / SQLite (local dev) |
| Job queue | Redis + arq (inline dev fallback without Redis) |
| PDF/docs | WeasyPrint (`services/worker`) |
| Telegram bot | aiogram 3 (`apps/bot`) |
| Bitcoin | BDK (`bdkpython 3.1.1`), public-descriptor persistence — selected via regtest proof (ADR D10) |
| Lightning | lnd v0.21.4-beta via pinned gRPC stubs — selected via two-node regtest drill (ADR D11) |

## Repository layout

```
xp/
├── apps/
│   ├── web/                  # Nuxt Mini App (wallet, XP, tasks, connections, automations…)
│   └── bot/                  # Telegram bot — 14-command router, deep links to Mini App
├── services/
│   ├── api/                  # FastAPI: /api/v1 (11 routers incl. ops)
│   ├── worker/               # arq worker: PDF/receipt jobs, agent runs, automation + retention crons
│   ├── agent-adapter/        # DSH: pinned revision, typed tool registry, PlanRunner
│   ├── wallet-adapter/       # BDK provider (regtest-proven), SigningBoundary, phrase vault
│   ├── lightning-adapter/    # lnd gRPC provider + canned semantics twin
│   ├── research-adapter/     # SSRF-walled fetch, typed facts, citations
│   ├── commerce-adapter/     # structural-only trend scoring
│   └── email-adapter/        # credential vault + canned/SMTP senders
├── packages/
│   ├── py-core/              # xp_core: models (23 tables), XP ledger, jobs (reconciliation, retention), rate limiter
│   ├── shared-types/         # TS contract types (mirrors API schemas)
│   └── api-client/           # typed fetch client used by the Mini App
├── scripts/                  # drills + audits + demo (committed, runnable)
├── infra/                    # docker-compose (Postgres+Redis), env templates
├── docs/                     # everything: threat model, IR runbooks, policies, decisions D1–D17
└── tests/                    # 266 pytest cases: invariants, forgery, allowlist, lifecycle, drills
```

## Local setup (zero external services)

```bash
cd xp
python3 -m venv .venv && .venv/bin/pip install -U pip
uv pip install --python .venv/bin/python -e packages/py-core -e services/api \
  -e services/worker -e services/agent-adapter -e services/wallet-adapter \
  -e services/lightning-adapter -e services/research-adapter \
  -e services/commerce-adapter -e services/email-adapter -e apps/bot
bun install

make migrate        # Alembic -> SQLite at data/xp-dev.db
make run-api        # FastAPI       http://127.0.0.1:8001  (/api/docs for OpenAPI)
make run-web        # Nuxt Mini App http://127.0.0.1:3000
```

## Real Bitcoin/Lightning test flows (regtest)

The canned providers are for hermetic dev/CI. The **real** flows are
committed drills that spawn their own regtest infrastructure:

```bash
make wallet-regtest    # BDK + bitcoind: create/fund/receive/send/restore roundtrip
make lightning-drill   # two lnd v0.21.4-beta nodes: invoice/payment/fee/SCB recovery (8 stages)
```

Both need a healthy host (bitcoind/lnd binaries); the lightning drill also
documents the btcwallet-stall limitation honestly instead of hiding it.

## With infrastructure (Postgres + Redis)

```bash
docker compose -f infra/docker-compose.yml up -d
export XP_DATABASE_URL=postgresql+asyncpg://xp:xp_dev_only@localhost:5432/xp
export XP_REDIS_URL=redis://localhost:6379/0
make migrate && make run-api
cd services/worker && ../../.venv/bin/arq worker.settings.WorkerSettings
```

## Telegram bot + Mini App

1. Create a bot with @BotFather, put the token in `XP_TELEGRAM_BOT_TOKEN`.
2. Point `XP_MINI_APP_URL` at your deployed Mini App.
3. `make run-bot` — `/start`, `/help`, `/xp` (live balance), and every
   security-sensitive flow deep-links into the Mini App. The bot never asks
   for seed phrases or private keys.

## Agent runtime (DeepSeek / DSH)

- `services/agent-adapter` is the ONLY path from the product to the model.
- Upstream revision pinned in `dsh_revision.json` with sha256 drift gate.
- Tools are allowlisted, typed, scoped, budgeted, and time-limited.
- Sensitive tools (`email.send`, `automation.schedule`) require explicit
  user approval (digest-bound, TTL-expiring approval records).
- Retrieved web content is wrapped as untrusted data; instructions inside it
  cannot override server authorization.
- Without `XP_DEEPSEEK_API_KEY` the adapter runs in deterministic stub mode —
  CI and local dev stay hermetic. `make dsh-verify` is the live proof
  (currently pending a key — KL-01).

## Tests & quality gates

```bash
make test           # 266 tests (invariants, forgery, scope wall, lifecycles, drills, demo)
make lint           # ruff
make audit          # dependency + container inventory, hard-pin gates
make backup-drill   # backup/restore roundtrip with ledger re-verification
```

## Security model

- **Self-custody is structural**: wallets persist PUBLIC descriptors only;
  the signing vault is in-memory with TTL; the agent cannot sign and the
  bot never asks for seeds. Evaluate the project without ever granting
  maintainers custody (plan phase-11 acceptance).
- **Money integrity**: append-only XP ledger, CAS balance transitions,
  idempotency-keyed settlement, 1:1 intent↔entry reconciliation with a
  persisted alert queue that critical findings cannot silently exit.
- **Authorization**: scope wall evaluated before approval gates; approval
  digests bind to exact content; untrusted content is wrapped and walled.
- Full model: `docs/threat-model.md` · internal review + findings:
  `docs/security-review.md` · responsible disclosure: `SECURITY.md`.

## Operations

- Rate limiting per route class with honest 429s (`XP_RATE_LIMIT_ENABLED`
  kill switch); reconciliation alert queue at `/api/v1/ops/*`
  (DEV_MODE-gated system seam); daily retention sweep that can never touch
  the ledger; incident runbooks R1–R6 in `docs/incident-response.md`;
  privacy windows in `docs/privacy-retention.md`.
- The complete "what is not production-proven" register:
  `docs/known-limitations.md`.

## Roadmap

Implemented vs. planned, phase by phase: `docs/roadmap.md`.

## Contributing

`CONTRIBUTING.md` — setup, quality bars, and the honesty principle that
gates every PR: no uncompleted feature may be represented as
production-ready.

## Btrust adoption

`docs/btrust-proposal.md` — why Bitcoin-native self-custody matters for AI
workforces, target users, architecture and security summary, and the
open-source maintenance plan.

## License & principles

Open source (license review pending — KL-14/phase-0 deliverable).
Non-negotiables from the plan: self-custody must be real and testable;
Telegram is an interface, not a key vault; the AI agent never receives seed
phrases or unrestricted signing authority; Bitcoin and XP are separate
ledgers; every financial transition is auditable and idempotent.
