# Development guide

## What you need

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- [bun](https://bun.sh) (Node 20+ also works for building)
- Docker, only if you want to run the full stack the way the server does

No API keys or accounts are needed for development or tests.

## First run

```bash
python3 -m venv .venv
make install        # Python packages and web dependencies
make migrate        # creates ./data/xp-dev.db (SQLite)
make run-api        # API on http://127.0.0.1:8001
make run-web        # app on http://127.0.0.1:3000
```

In development, dev mode signs you in without Telegram, and background jobs run inside the API when Redis isn't set. Optional: `make run-worker` (needs Redis) and `make run-bot` (needs a bot token).

## Tests

```bash
make test                         # server tests (pytest)
cd apps/web && bun test tests     # wallet tests
make lint                         # code style (ruff)
make demo                         # a quick end-to-end run of the server, no outside services
```

## Building

```bash
cd apps/web && bun run build          # the Mini App
bun run build:extension               # the browser extension: apps/extension/dist + satish-extension.zip
```

For the extension, set `SATISH_API` (your server's address) and `SATISH_BOT` (your bot's username) first. See [apps/extension/README.md](../apps/extension/README.md).

## Settings

Server settings are environment variables with the `XP_` prefix (kept from the project's early name so existing servers keep working). They are defined in `packages/py-core/xp_core/config.py`, and the ones you need for a real server are explained in [deploy/.env.example](../deploy/.env.example).

| Setting | Default | |
|---|---|---|
| `XP_ENV` | `dev` | `dev`, `regtest`, `testnet`, `staging` or `prod` |
| `XP_DEV_MODE` | `false` | signs in without Telegram. Refused in staging and prod |
| `XP_DATABASE_URL` | SQLite | or `postgresql+asyncpg://...` |
| `XP_REDIS_URL` | unset | turns on the background workers |
| `XP_TELEGRAM_BOT_TOKEN` | unset | real Telegram sign-in and the bot |
| `XP_DEEPSEEK_API_KEY` | unset | real Satish AI answers |
| `XP_TK_WALLET_MNEMONIC` | unset | the operator wallet that receives TK and developer Lightning payments |

The app's settings start with `NUXT_PUBLIC_` (network, Breez key, API address, Esplora server).

## Database changes

```bash
cd services/api
../../.venv/bin/alembic revision --autogenerate -m "what changed"
../../.venv/bin/alembic upgrade head
../../.venv/bin/alembic downgrade -1 && ../../.venv/bin/alembic upgrade head   # check it undoes cleanly
```

Amounts are whole sats and whole TK, never decimals. Times are stored in UTC.

## Testing the wallet by hand

- Bitcoin test coins: [mempool.space testnet4 faucet](https://mempool.space/testnet4/faucet)
- Lightning test coins: [Lightspark regtest faucet](https://app.lightspark.com/regtest-faucet)
- To test against your own chain server, set `NUXT_PUBLIC_ESPLORA_URL`.

## Problems

| Problem | Fix |
|---|---|
| `unable to open database file` | use an absolute SQLite path: `sqlite+aiosqlite:////full/path/xp.db` |
| PDF errors | install Pango: `apt install libpango-1.0-0 libpangoft2-1.0-0` |
| The bot stops straight away | set `XP_TELEGRAM_BOT_TOKEN` |
| Jobs never run | set `XP_REDIS_URL` and run the workers, or leave it unset in dev |
| The extension won't load | rebuild it; Chrome refuses files whose names start with `_`, and the build checks for that |
