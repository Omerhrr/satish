# Architecture

## The pieces

```
 ┌───────────────┐  ┌─────────────────┐  ┌───────────────────┐
 │ Telegram bot  │  │ Mini App        │  │ Browser extension │
 │ (apps/bot)    │  │ (apps/web)      │  │ (apps/extension)  │
 └──────┬────────┘  └────────┬────────┘  └─────────┬─────────┘
        │                    │  the wallet runs here: keys,
        │                    │  signing, Bitcoin + Lightning
        │                    │                     │
        │                    └──────────┬──────────┘
        │                               │ signed-in API calls (never keys)
        ▼                               ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Satish server (services/api, FastAPI)                    │
 │  Wallet services   @usernames, payment requests,         │
 │                    group pay, alerts, rates              │
 │  Developer API     keys, payment requests, webhooks,     │
 │                    Lightning hand-on, demo shop          │
 │  Satish AI         chat, tasks, research, TK credits     │
 │                    (separate, no wallet access)          │
 └──────┬───────────────────┬──────────────────┬────────────┘
        │                   │                  │
   SQLite/Postgres     Redis + workers     Operator Lightning wallet
                       (worker, ai-worker)  (Breez Spark, receives TK
                                             and developer payments)

 Outside services: mempool.space (Bitcoin data), Breez/Spark (Lightning),
 DeepSeek (AI model), Brave Search, CoinGecko (rates), Onramper (buy bitcoin)
```

## What runs where

| Part | Where | Holds |
|---|---|---|
| Wallet | on the person's device, in the Mini App or extension | the encrypted recovery phrase, signing, Bitcoin and Lightning |
| Bot | server (`bot` container) | Telegram commands, chat with Satish AI, group pay cards, sign-in codes for the extension |
| API | server (`api` container) | accounts, @usernames and signed address pools, payment requests, developer API, TK ledger, Satish AI |
| Worker | server (`worker`) | payment checks, alerts, webhooks, Telegram messages, automations, clean-up |
| AI worker | server (`ai-worker`) | Satish AI tasks, on their own queue |
| Web | server (`web`) | serves the Mini App |

## Trust boundaries

1. **Device and server.** Keys never cross. The server gets only what it needs to help: signed receive addresses for @usernames, the addresses someone asks it to watch for alerts, and a signed Lightning address.
2. **Telegram and server.** Telegram login data is checked with the bot token on every sign-in. Sessions last 24 hours (30 days for the extension) and can be revoked.
3. **Satish AI and everything else.** The AI only gets its own tools. It can't import wallet code, and its actions that reach outside Satish need the person's approval.
4. **Developers and Satish.** API keys can only create and read their owner's payment requests. Webhooks are signed and only go to public `https://` addresses.
5. **The operator wallet.** The one place the server holds a key that can spend: the operator's Lightning wallet (and, if `XP_TK_WALLET_MNEMONIC` is used, the operator's own TK wallet). It receives TK and developer Lightning payments, so keep only a small amount there.

## Data

The server database holds accounts and Telegram links, sessions, @usernames and their address pools, payment requests, developer keys (hashed) and webhooks, group payments, alert subscriptions, the TK ledger, Satish AI tasks and memories, and an audit trail.

It holds **no recovery phrases, no private keys and no balances**. Wallet tables from an early server-side wallet remain empty so old migrations still run.

Rules that matter for money:

- The TK ledger is append-only, and a balance can never go below zero.
- Each payment credits once: a compare-and-set marks it settled, and the ledger entry has a unique key.
- A reconciliation job checks balances against the ledger and raises alerts.

## Code layout

```
apps/web            Nuxt 4 app (Mini App + extension build)
  app/lib           wallet core: keys, signing, Lightning, backup, Shamir
apps/extension      extension manifest, background script, build
apps/bot            Telegram bot (aiogram)
services/api        FastAPI server
services/worker     background jobs (arq)
services/agent-adapter, research-adapter, commerce-adapter, email-adapter
                    Satish AI's model client and tools
services/lightning-adapter
                    payment provider interfaces used by the TK purchase flow
services/chart-renderer
                    turns chart specs into images for PDFs and Telegram
packages/py-core    shared models, ledger, settings, services
packages/api-client typed client used by the app
deploy              Docker, Caddy, settings template
```
