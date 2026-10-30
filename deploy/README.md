# Deploying Satish (Docker and Caddy)

The server runs six containers: `api`, `worker` (payments, alerts, webhooks, automations), `ai-worker` (Satish AI tasks), `bot`, `web` (the Mini App) and `redis`.

Only `api` (127.0.0.1:18431) and `web` (127.0.0.1:18432) are published, and only on localhost. Caddy is the single public entry. The database and files live in the `satish_xp_data` volume.

## 1. DNS

Point your domain (for example `satish.example.com`) at the server. With Cloudflare's proxy on, use SSL mode **Full (strict)**; "Flexible" causes redirect loops. DNS-only is simplest.

## 2. Code and settings

```bash
git clone https://github.com/Omerhrr/satish.git && cd satish/deploy
cp .env.example .env && nano .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # run it twice, for the two secret keys
```

Every setting is explained in `.env.example`. The main ones:

| Setting | What it does |
|---|---|
| `PUBLIC_URL`, `XP_MINI_APP_URL` | your domain |
| `BITCOIN_NETWORK` | `testnet` (free test coins) or `mainnet` (real bitcoin). Set `XP_ONCHAIN_NETWORK` to match |
| `XP_TELEGRAM_BOT_TOKEN`, `BOT_USERNAME` | your bot, from @BotFather |
| `BREEZ_API_KEY` | needed for Lightning on mainnet. Free from [breez.technology](https://breez.technology/request-api-key/) |
| `XP_TK_WALLET_MNEMONIC` | the 12 words of a Satish wallet **used only for income**. It receives TK purchases and developer Lightning payments (then forwards those). It can spend that wallet, so keep a small balance and move money out often |
| `XP_TK_PAYEE_USERNAME` | that wallet's @username, shown to payers |
| `XP_OPS_OPERATOR_TOKEN`, `XP_CONNECTIONS_CREDENTIAL_KEY` | the two secret keys you generated |
| `XP_DEEPSEEK_API_KEY` | real Satish AI answers ([platform.deepseek.com](https://platform.deepseek.com)) |
| `XP_BRAVE_SEARCH_API_KEY` | better web research ([api-search.brave.com](https://api-search.brave.com), free tier) |
| `XP_ONRAMPER_API_KEY`, `XP_ONRAMPER_SIGNING_KEY` | buy bitcoin with naira (mainnet). `python3 onramper_keys.py` makes the signing key |
| `XP_TELEGRAM_MINIAPP_SHORT_NAME` | lets group chat buttons open Satish inside Telegram (or set the bot's Main Mini App in BotFather) |

Settings keep the `XP_` prefix from the project's early name, so existing servers keep working.

## 3. Start

```bash
docker compose up -d --build
docker compose ps                  # all six running, api "healthy"
curl -s 127.0.0.1:18431/healthz
```

## 4. Caddy

Add `Caddyfile.snippet` (with your domain) to your Caddyfile and run `sudo systemctl reload caddy`. Then open `https://your-domain/healthz`.

If Caddy itself runs in Docker, `127.0.0.1` is Caddy's own container: connect it to this project's network (`docker network connect satish_default <caddy container>`) and proxy to `api:8001` and `web:3000` instead.

## 5. Telegram

In @BotFather: your bot > Bot Settings > Menu Button > your domain. For group chat buttons, also set Configure Mini App (or use `XP_TELEGRAM_MINIAPP_SHORT_NAME`). Set the bot's picture with `/setuserpic` and `brand/satish-logo-640.png`. Then `/start` the bot and tap **Open Satish**.

## Day to day

```bash
docker compose logs -f api bot             # watch
git pull && docker compose up -d --build   # update (database changes apply on start)
docker compose down                        # stop (the data volume is kept)
```

Back up the `satish_xp_data` volume regularly. What to do when things go wrong: [docs/operations.md](../docs/operations.md).

## Safety

- Keep `XP_DEV_MODE=false`. Dev mode skips Telegram sign-in; it is refused when `XP_ENV` is `staging` or `prod`.
- Keep `XP_DEMO_LIGHTNING_SETTLE=false` on any server taking real payments.
- The income wallet's phrase is the one secret here that can move money. Treat the server like a hot wallet.
