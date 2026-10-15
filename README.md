# XP — Bitcoin-Native Telegram AI Workforce

Open-source, Telegram-native Bitcoin self-custody wallet and AI work platform.
Users pay for research, business intelligence, document creation, and approved
automations using sats converted into application usage credits called **XP**.

> **Status: Phase 1 scaffold** (repository & developer foundation). See
> `docs/decisions.md` for what is real vs. pending. Adoption-preparation goal:
> independently reviewable, threat-model-driven, no overclaims.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Nuxt 4 + Vue + TypeScript (`apps/web`, Telegram Mini App) |
| Backend | FastAPI + Python 3.12 (`services/api`) |
| Agent runtime | DeepSeek via controlled DSH adapter (`services/agent-adapter`) |
| Database | PostgreSQL (prod) / SQLite (local dev) |
| Job queue | Redis + arq (inline dev fallback without Redis) |
| PDF/docs | WeasyPrint (`services/worker`) |
| Telegram bot | aiogram 3 (`apps/bot`) |
| Bitcoin/Lightning | Adapter protocols only until the phase-3 spikes |

## Repository layout

```
xp/
├── apps/
│   ├── web/                  # Nuxt Mini App (wallet, XP ledger, tasks, security)
│   └── bot/                  # Telegram bot — 14-command router, deep links to Mini App
├── services/
│   ├── api/                  # FastAPI: /api/v1, auth, XP ledger, tasks, artifacts
│   ├── worker/               # arq worker: WeasyPrint PDF jobs (bounded, retryable)
│   ├── agent-adapter/        # DSH adapter: typed tool registry, DeepSeek client, PlanRunner
│   ├── wallet-adapter/       # WalletProvider protocol + regtest stub + SigningBoundary
│   └── lightning-adapter/    # LightningProvider protocol + stub
├── packages/
│   ├── py-core/              # shared Python: settings, logging, models, XP ledger, storage
│   ├── shared-types/         # TS contract types (mirrors API schemas)
│   └── api-client/           # typed fetch client used by the Mini App
├── infra/                    # docker-compose (Postgres+Redis), env templates
├── docs/                     # development, architecture, decisions, threat model
└── tests/                    # pytest: ledger invariants, auth, registry, API contract
```

## Quickstart (zero external services)

```bash
cd xp
python3 -m venv .venv && .venv/bin/pip install -U pip
uv pip install --python .venv/bin/python -e packages/py-core -e services/api \
  -e services/worker -e services/agent-adapter -e services/wallet-adapter \
  -e services/lightning-adapter -e apps/bot
bun install

make migrate        # Alembic -> SQLite at data/xp-dev.db
make run-api        # FastAPI      http://127.0.0.1:8001  (/api/docs for OpenAPI)
make run-web        # Nuxt Mini App http://127.0.0.1:3000
```

Open the Mini App: seed XP with one click, watch the append-only ledger, run a
task with atomic budget reservation, and generate a WeasyPrint PDF through the
worker pipeline.

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
- Tools are allowlisted, typed, scoped, budgeted, and time-limited.
- Sensitive tools (`email.send`, `automation.schedule`) require explicit
  user approval (digest-bound approval records).
- Retrieved web content is wrapped as untrusted data; instructions inside it
  cannot override server authorization.
- Without `XP_DEEPSEEK_API_KEY` the adapter runs in deterministic stub mode —
  CI and local dev stay hermetic. Upstream DSH revision gets pinned in the
  phase-0 integration spike (`XP_DSH_REVISION`).

## Tests & quality gates

```bash
make test    # 32 tests: ledger invariants, initData forgery, tool allowlist, API contract
make lint    # ruff
```

## Documentation

- `docs/development.md` — environment, migrations, service topology
- `docs/architecture.md` — components, trust boundaries, data model
- `docs/threat-model.md` — assets, adversaries, mitigations, release gates
- `docs/decisions.md` — decision log incl. what is deliberately NOT done yet
- `docs/research-tools.md` — phase-7 research pipeline: permission wall, provenance, quality gates, evaluation set
- `docs/commerce-intelligence.md` — phase-8 commerce intelligence: transparent scoring, supplier/vehicle research, ad-library honesty, landed-cost template, freshness/confidence

## License & principles

Open source (license review pending phase 0). Non-negotiables from the plan:
self-custody must be real and testable; Telegram is an interface, not a key
vault; the AI agent never receives seed phrases or unrestricted signing
authority; Bitcoin and XP are separate ledgers; every financial transition is
auditable and idempotent.
