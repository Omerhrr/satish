<p align="center"><img src="brand/satish-logo-640.png" alt="Satish" width="120"></p>

# Satish

**A self-custodial Bitcoin and Lightning wallet that lives in Telegram and in your browser, with payments any app can plug into.**

Your keys are made on your device and never leave it. You can hold bitcoin, pay people by @username in seconds over Lightning, share payment links, split bills in a group chat, and let shops and apps take payment with "Pay with Satish".

**Satish AI** is the first app built on Satish payments: a research assistant you pay for in bitcoin, through TK credits. It shows what any developer can build on the same payment API. It is a separate app that uses Satish to get paid, not part of the wallet, and it can never touch anyone's wallet.

Built for the Btrust Build-A-thon at DevFest Kaduna 2026 · MIT licensed · [Proposal for Btrust](docs/btrust-proposal.md)

## The wallet

- **Yours alone.** Create or restore with 12 words. The phrase is made on your phone, encrypted with your password, and never sent to the Satish server. The server has no way to move anyone's money.
- **Bitcoin and Lightning, one backup.** Savings on the Bitcoin network; instant, near-free payments on Lightning (Breez SDK on Spark). Both come from the same 12 words.
- **Pay people, not addresses.** Claim `@ada` and anyone can pay you by name. Each payment still goes to a fresh address that the payer's phone checks really belongs to you.
- **Money the way you think about it.** Type amounts in sats, naira, dollars or any currency. Twelve languages, including Hausa, Yoruba, Igbo and Pidgin.
- **Get paid.** Payment links that work in WhatsApp and with any wallet, QR codes, group payments and bill splits in Telegram chats.
- **Safe on bad days.** Encrypted backup to your own Telegram, social recovery with trusted people (any 2 of 3), speed up or cancel a stuck payment, a daily spending limit, warnings before risky payments, an app lock.
- **Never locked in.** A standard BIP84 wallet: export to Sparrow and other wallets, or move everything out in one tap.
- **Two ways to open it.** As a Telegram Mini App, or as a browser extension (Chrome, Edge, Brave) signed in with the same account.

## Satish for developers

Any website, app or bot can take payment with Satish:

1. Create an API key in **Wallet > Settings > Developers**.
2. Your server creates a payment request (in sats or any currency).
3. Show the shopper the Satish pay page or its QR codes. They pay by Lightning or Bitcoin, from Satish or any other wallet.
4. Satish calls your webhook with `request.paid`.

Bitcoin payments go straight to the developer's own wallet. Lightning payments are received by Satish and passed on to the developer's Lightning wallet within seconds. A working demo shop, **Kaduna Kicks**, shows the whole flow in a normal browser tab. Details: [docs/developers.md](docs/developers.md).

## Satish AI, the first app on Satish payments

Ask questions, get research with sources, comparisons, charts and PDF reports, in the app or by chatting with the bot. It runs on TK credits: every account gets 300 TK, and more is bought at 1 sat = 5 TK, paid by Lightning or Bitcoin into the operator's own Satish wallet. Details: [docs/satish-ai.md](docs/satish-ai.md).

## How it fits together

```
Telegram bot ──┐
Mini App ──────┼── on your device: keys, signing, Bitcoin + Lightning wallet
Extension ─────┘          │
                          │ signed-in calls (never keys)
                          ▼
                 Satish server (FastAPI)
                 ├─ @usernames, payment requests, group pay, alerts
                 ├─ developer API, webhooks, Lightning hand-on
                 └─ Satish AI (separate, isolated) + TK credits
                 SQLite or PostgreSQL · Redis + background workers
```

More: [docs/architecture.md](docs/architecture.md).

## Try it

- **Telegram:** open the Satish bot and tap **Open Satish**. On the test network, coins are free from the [mempool.space testnet4 faucet](https://mempool.space/testnet4/faucet), and Lightning test coins from the [Lightspark regtest faucet](https://app.lightspark.com/regtest-faucet).
- **Browser:** load the extension from `apps/extension` ([how](apps/extension/README.md)).
- **Run your own server:** [deploy/README.md](deploy/README.md).

## Develop

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/) and [bun](https://bun.sh).

```bash
python3 -m venv .venv
make install && make migrate
make test                          # server tests
cd apps/web && bun test tests      # wallet tests
make run-api                       # API on :8001
make run-web                       # app on :3000
```

Full guide: [docs/development.md](docs/development.md). How to help: [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

All docs are listed in [docs/README.md](docs/README.md). Start with [what's not finished yet](docs/known-limitations.md) and the [threat model](docs/threat-model.md).

## Security

Found a problem? Please report it privately: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 The Satish contributors
