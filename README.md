# Satish: your own Bitcoin wallet, inside Telegram

**In plain words:** Satish is a Telegram app with your own Bitcoin wallet in it.
Your keys stay on your phone. You can receive, send, buy bitcoin with naira,
and pay for an AI assistant that does research and writes reports, all
without handing your money to anyone.

Built for the Btrust Build-A-thon at DevFest Kaduna City '26 · MIT licensed ·
[Btrust proposal](docs/btrust-proposal.md)

## What a user can do

- **Own a real Bitcoin wallet.** Create or restore with 12 words; the phrase
  is made on the phone and encrypted with your password. Satish's server never
  sees it and has no wallet endpoints at all.
- **Receive, send, save contacts.** QR codes, fee choice (Fast/Normal/Slow),
  a full review before every payment, and an address book so you can pay
  "Mum" instead of a 42-character address.
- **Lightning for everyday spending.** A Lightning wallet on the phone (Breez
  SDK on Spark) with the same 12 words: instant payments with tiny fees,
  invoices, Lightning addresses, and one-tap moves between savings and
  Lightning.
- **Pay people by @username.** Claim `@ada` and friends pay you by name;
  every payment still lands at a fresh address in your own wallet, and the
  sender's phone verifies the address really belongs to you.
- **Share payment links.** "@ada is requesting 5,000 sats for rice": one link
  you can drop into WhatsApp, payable from any bitcoin wallet, with a
  Telegram message when it's paid.
- **Buy bitcoin with naira** through licensed partners (Onramper) that send
  it straight to your own address.
- **See naira values** next to your balance and payments.
- **Back up to your own Telegram**, encrypted with your password, and restore
  on a new phone. Restoring finds every payment, including ones made to your
  @username.
- **Fix a stuck payment.** Speed it up with a higher fee, or cancel it while
  it's still waiting.
- **Get a Telegram message when bitcoin arrives** (opt-in), and again when it
  confirms.
- **Stay safe.** Warnings before paying a new address or a large amount,
  optional app lock, hide balance, notes on payments, CSV history, and a
  plain "forgot password" path.
- **Never locked in.** Standard BIP84 wallet: export the public key or
  descriptor to Sparrow and others, move everything out in one tap, and read
  the recovery and family guide in the app.
- **Pay for AI work with bitcoin.** Buy TK credits in one tap from your
  wallet, then ask for research, comparisons or a PDF report with sources.
  You approve a budget first and unused TK comes back. TK can only be
  spent on tasks: it can't be sent to anyone or turned back into sats.

## How it fits together

```
 Telegram ── Bot (aiogram) ─────────┐
          └─ Mini App (Nuxt 4) ─────┤  wallet keys + signing stay HERE (on the phone)
                │  ▲                │
     chain data │  │ broadcast      │ signed-in API calls (no keys, ever)
                ▼  │                ▼
          mempool.space        FastAPI (services/api)
                ▲              ├─ TK ledger: append-only, exactly-once credits
                │ watch-only   ├─ TK payments: fresh address per purchase,
                └──────────────┤    derived from the operator's PUBLIC key
                               ├─ AI agent (DeepSeek), budgets + approvals
                               ├─ research (Brave Search), PDFs (WeasyPrint)
                               └─ buy-bitcoin link signing (Onramper)
                        PostgreSQL or SQLite · Redis + arq worker
```

Design decisions and their reasons: [`docs/decisions.md`](docs/decisions.md)
(D22-D26 cover the wallet, payments, buying, backup and fail-closed dev mode).
What is not finished yet: [`docs/known-limitations.md`](docs/known-limitations.md).

## Try it

- **On Telegram:** open the Satish bot and tap **Open Satish** (testnet4: coins are free
  from the [mempool.space faucet](https://mempool.space/testnet4/faucet)).
- **Deploy your own:** [`deploy/README.md`](deploy/README.md) (Docker Compose
  behind Caddy). Settings are documented in
  [`deploy/.env.example`](deploy/.env.example).

## Develop

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), [bun](https://bun.sh).

```bash
python3 -m venv .venv
make install            # Python packages + web dependencies
mkdir -p data && make migrate
make test               # server tests
cd apps/web && bun test tests   # wallet tests (BIP84 vectors, signing, backup)
make demo               # end-to-end demo, no external services
make run-api            # API on :8001 (dev mode on locally)
make run-web            # Mini App on :3000
```

`uv pip install --python .venv/bin/python pytest pytest-asyncio` adds the test tools.

## Repository layout

```
apps/web/          Telegram Mini App (wallet, Buy TK, tasks, settings)
  app/lib/         wallet-core.ts (keys, signing, coin selection), cloud-backup.ts
apps/bot/          Telegram bot
services/api/      FastAPI app: auth, TK, tasks, payments, onramp, price, ops
services/worker/   background jobs: PDFs, agent runs, payment sweep, retention
services/*-adapter AI agent, research, commerce, email, Lightning, Telegram relay
packages/py-core/  shared models, ledger, on-chain payment watcher, settings
deploy/            Dockerfiles, compose, Caddy snippet, env template, key helpers
docs/              decisions, threat model, security review, runbooks, proposal
tests/             server tests
```

## Security model, briefly

- Wallet keys exist only on the user's device; the AI agent and the server
  are not in the signing path.
- The operator's payment wallet is watch-only on the server.
- TK credits are idempotent and reconciled against payments.
- Dev mode is off by default and refused in production; operator endpoints
  need a credential and are audited.
- Full threat model: [`docs/threat-model.md`](docs/threat-model.md);
  responsible disclosure: [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE)
