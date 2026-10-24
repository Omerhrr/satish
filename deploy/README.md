# Deploying XP to a VPS (Docker + host Caddy)

Containers: `api`, `worker`, `bot`, `web`, `redis`. Only `api` (127.0.0.1:18431)
and `web` (127.0.0.1:18432) are published, and only on localhost: Caddy is the
single public entry. Data (SQLite DB, PDFs, wallet descriptors) lives in the
`satish_xp_data` volume.

## 1. DNS (Cloudflare)
`satish.rogan.live` A record -> VPS IP. Proxied (orange) is fine only with
SSL/TLS mode **Full (strict)**; "Flexible" causes redirect loops. Grey cloud
(DNS only) is the simplest.

## 2. Code + secrets
```bash
git clone -b fix/telegram-login-and-deps https://github.com/Omerhrr/satish.git && cd satish
cd deploy && cp .env.example .env && nano .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # run twice, for the two keys
```

## 2b. Feature keys (all optional, each switches one thing on)

| Setting | What it does | Where to get it |
|---|---|---|
| `XP_ONCHAIN_XPUB` | Real XP payments in bitcoin to **your** wallet | `python3 deploy/make_payment_wallet.py testnet` on your own computer. Keep the 12 words offline; only the public key goes on the server |
| `XP_DEEPSEEK_API_KEY` | Real AI answers | platform.deepseek.com |
| `XP_BRAVE_SEARCH_API_KEY` | Real web research | api-search.brave.com (free tier) |
| `XP_ONRAMPER_API_KEY` + `XP_ONRAMPER_SIGNING_KEY` | Buy bitcoin with naira in the app (mainnet) | onramper.com; `python3 deploy/onramper_keys.py` makes the signing key |
| `BOT_USERNAME` | "Pay with XP on Telegram" button on shared payment links | your bot's username, without @ |
| `BITCOIN_NETWORK` | `testnet` (free test coins) or `mainnet` (real bitcoin) | set `XP_ONCHAIN_NETWORK` to match |

## 3. Start
```bash
docker compose up -d --build
docker compose ps                 # api should become "healthy"
curl -s 127.0.0.1:18431/healthz
```

## 4. Caddy
Append `Caddyfile.snippet` to your Caddyfile, `sudo systemctl reload caddy`,
then open https://satish.rogan.live/healthz.

Caddy itself in Docker? Then 127.0.0.1 is Caddy's own container. Attach Caddy
to this project's network (`docker network connect satish_default <caddy>`)
and proxy to `api:8001` / `web:3000` instead.

## 5. Telegram
@BotFather -> `/mybots` -> your bot -> Bot Settings -> Menu Button ->
`https://satish.rogan.live`. Then `/start` the bot and tap Open.

## Day-to-day
```bash
docker compose logs -f api bot             # watch
git pull && docker compose up -d --build   # update
docker compose down                        # stop (data volume is kept)
```

## Security notes
- `XP_DEV_MODE=false`: real Telegram login only. Dev mode is now off by
  default and refused outright when `XP_ENV=staging|prod`.
- `XP_DEMO_LIGHTNING_SETTLE=true` lets the demo "settle" button credit XP with
  the canned (fake) Lightning provider. Turn it off before taking real payments.


### Services

`api`, `worker` (payments, alerts, automations), `ai-worker` (Satish AI tasks,
its own queue), `bot`, `web`, `redis`. After `docker compose up -d --build`,
`docker compose ps` should list all six as running. If Satish AI tasks say
"Waiting to start", check `docker compose logs ai-worker --tail 50`.
