# Development Guide

## Prerequisites

- Python 3.11+ (3.12 recommended), [uv](https://docs.astral.sh/uv/) for fast installs
- Node 20+ / Bun 1.1+ for the Nuxt workspace
- Docker (optional — only for Postgres/Redis infrastructure)

## First run (zero infrastructure)

```bash
python3 -m venv .venv
uv pip install --python .venv/bin/python -e packages/py-core -e services/api \
  -e services/worker -e services/agent-adapter -e services/wallet-adapter \
  -e services/lightning-adapter -e services/research-adapter -e apps/bot
bun install

make migrate      # alembic upgrade head (SQLite: ./data/xp-dev.db)
make run-api      # http://127.0.0.1:8001
make run-web      # http://127.0.0.1:3000
make audit        # dependency + container audit gates (phase 10)
make backup-drill # backup/restore roundtrip drill (phase 10)
make demo         # reproducible end-to-end golden-path demo (phase 11)
```

Local dev requires no production secrets: DEV_MODE issues a dev user session,
jobs run inline when Redis is absent, and SQLite keeps the data model honest.

## Configuration

All settings are env-driven with the `XP_` prefix (see
`packages/py-core/xp_core/config.py` and `infra/env/.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `XP_ENV` | `dev` | dev / regtest / testnet / staging / prod |
| `XP_DEV_MODE` | `true` | relaxes auth + enables dev grants (never in prod) |
| `XP_DATABASE_URL` | sqlite | `postgresql+asyncpg://…` in shared envs |
| `XP_REDIS_URL` | unset | enables arq; unset → inline job execution |
| `XP_ARTIFACT_DIR` | `./data/artifacts` | local object storage root |
| `XP_TELEGRAM_BOT_TOKEN` | unset | enables initData validation + bot |
| `XP_SATS_PER_XP` | `10` | published conversion rate |
| `XP_DEEPSEEK_API_KEY` | unset | unset → agent adapter stub mode |

## Migrations

```bash
cd services/api
XP_DATABASE_URL=postgresql+asyncpg://… ../../.venv/bin/alembic revision --autogenerate -m "…"
XP_DATABASE_URL=… ../../.venv/bin/alembic upgrade head
```

Migrations are reviewable and reversible (data_rules #4). The initial
revision creates all 16 tables of the plan's data model.

## Service topology

| Service | Command | Port |
|---|---|---|
| FastAPI | `make run-api` | 8001 |
| Nuxt Mini App | `make run-web` | 3000 |
| arq worker | `make run-worker` | — |
| Telegram bot | `make run-bot` | — (needs token) |

Frontend → API transport: `packages/api-client` supports direct mode
(`NUXT_PUBLIC_API_BASE=http://127.0.0.1:8001`) and same-origin gateway mode
(`NUXT_PUBLIC_API_PORT=8001` → requests carry `?XTransformPort=8001`), which
is how the sandbox preview works behind a single exposed port.

## Data model notes

- UTC timestamps everywhere; user-local rendering happens in the UI.
- Integer satoshis and integer XP — never floats for financial accounting.
- `xp_ledger_entries` is append-only; `xp_accounts.balance` always equals
  `SUM(entries)` per user (enforced by tests).
- Wallet tables hold **metadata only** — no seed or private-key columns exist
  by design.

## Troubleshooting

- `unable to open database file` → use an absolute `sqlite+aiosqlite:////abs/path.db` URL.
- WeasyPrint needs pango/cairo system libs (`apt install libpango-1.0-0 libpangoft2-1.0-0`).
- Bot exits immediately → set `XP_TELEGRAM_BOT_TOKEN`.
- Worker does nothing → either set `XP_REDIS_URL` and run the worker, or let
  the API run jobs inline (dev mode).
