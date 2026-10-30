# Contributing to Satish

Thanks for wanting to help. Satish is a self-custodial wallet, so the bar is simple: **never put people's money at risk, and never claim something works when it doesn't.**

## Get set up

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and [bun](https://bun.sh). No accounts or API keys are needed to run the tests.

```bash
git clone https://github.com/Omerhrr/satish.git && cd satish
python3 -m venv .venv
make install        # Python packages and web dependencies
make migrate        # creates the local SQLite database
make test           # server tests
cd apps/web && bun test tests   # wallet tests
```

To run the app locally, see [docs/development.md](docs/development.md).

## Before you open a pull request

| Check | Command |
| --- | --- |
| Server tests pass | `make test` |
| Wallet tests pass | `cd apps/web && bun test tests` |
| Code style | `make lint` |
| The app builds | `cd apps/web && bun run build` |
| The extension builds (if you touched the app) | `bun run build:extension` |
| Database changes migrate up and down | `cd services/api && alembic upgrade head && alembic downgrade -1 && alembic upgrade head` |

## Ground rules

1. **Keys never leave the device.** Nothing may send a recovery phrase, private key or the wallet's public key (xpub) to the server. The server must stay unable to move anyone's money.
2. **Satish AI stays away from wallets.** The AI may not import wallet code or get wallet tools (`tests/test_ai_isolation.py` checks this). Paying someone is always a wallet action the person does themselves.
3. **Money code is careful code.** TK balances only change through the append-only ledger, each payment credits exactly once, and anything that could double-pay or double-credit needs a test that proves it can't.
4. **Say what's real.** If something only works on the test network, or depends on a key that may not be set, the app and the docs must say so. Add open gaps to [docs/known-limitations.md](docs/known-limitations.md).
5. **Security changes need a test.** That covers sign-in, keys, signing, webhooks, the developer API and anything that touches money. If the change moves a trust boundary, update [docs/threat-model.md](docs/threat-model.md).
6. **New dependencies need a reason** in the pull request, and an exact version.
7. **Database changes** go through an Alembic migration that can be undone.
8. **Docs change with the code.** If your change alters something described in `docs/`, update it in the same pull request.
9. **Plain words.** Text people see should be short and clear, and work in translation. No em dashes.

## Where things live

| Area | Path |
| --- | --- |
| Wallet (keys, signing, Bitcoin, Lightning, backup) | `apps/web/app/lib`, `apps/web/app/composables` |
| App screens | `apps/web/app/pages`, `apps/web/app/components` |
| Browser extension build | `apps/extension` |
| Telegram bot | `apps/bot` |
| Server API | `services/api/app` |
| Background jobs | `services/worker` |
| Satish AI (agent, research, tools) | `services/agent-adapter`, `services/research-adapter`, `services/api/app/services` |
| Shared models, ledger, settings | `packages/py-core` |
| Deployment | `deploy` |

The project has one maintainer today (@Omerhrr). As people contribute regularly, we'll share ownership of areas.

## Commits

One change per commit. Say what changed and why.

## Reporting bugs

Open a GitHub issue with steps to reproduce. Security problems go through [SECURITY.md](SECURITY.md), not public issues.
