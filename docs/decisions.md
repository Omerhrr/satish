# Design decisions

The decisions that shape Satish today, and why. Earlier, superseded choices are in the git history.

## 1. The wallet lives on the device, not the server

An early version kept the wallet on the server, which needed the recovery phrase to sign. That is not self-custody. Now keys are made, stored (encrypted with the person's password) and used only on the device, with `@scure/bip39`, `@scure/bip32` and `@scure/btc-signer`. The server has no wallet keys and no wallet endpoints. Bitcoin data comes from an Esplora server (mempool.space by default).

**Trade-off:** losing the phone means restoring from the 12 words (or the Telegram backup). The Esplora server sees which addresses are looked up.

## 2. Lightning on the device with the Breez SDK on Spark

Small payments need Lightning, but running a Lightning node for every user would mean holding liquidity and operating channels, and a custodial Lightning account would break the self-custody promise. The Breez SDK on Spark runs in the app (WebAssembly), from the same 12 words.

**Trade-off:** Spark transfers are co-signed by independent operators. They can't take funds and people can always exit on-chain, but it is a weaker guarantee than plain Bitcoin. The app explains this.

## 3. One password opens both wallets

"Unlock Satish" decrypts the phrase once per session for Bitcoin and Lightning. Showing the words, exporting keys and changing the password ask again. Locking forgets it.

## 4. @usernames without giving the server the xpub

The phone uploads a pool of its own receive addresses, each signed by a wallet identity key that can vouch for addresses but can't spend. The server hands out one per payment; the payer's phone checks the signature and remembers the key. Lightning addresses are published the same way.

**Trade-off:** the server learns which payments went to which username, but not balances or anything else.

## 5. Encrypted backup to the person's own Telegram, and social recovery

The phrase can be stored in Telegram Cloud Storage, encrypted with the same password; the address book syncs with its own key. Separately, the phrase can be split 2-of-3 among trusted people (Shamir's secret sharing with a checksum).

## 6. Safety for real life

An "I've checked" step for new addresses, large amounts and high fees; a daily spending limit that delays large sends by 30 seconds; app lock; fixing stuck payments with replace-by-fee; a recovery and family guide; export to other wallets. On mainnet, the app suggests keeping savings elsewhere above 1,000,000 sats until there has been an independent review.

## 7. Money in local terms

Amounts can be typed in sats or any currency (live rates from CoinGecko and open.er-api.com). What is sent is always the sats shown at that moment. The app speaks 12 languages, and Satish AI answers in the person's language.

## 8. Two ways to open Satish: Telegram and the browser

One Nuxt app, two builds. The browser extension (Manifest V3, side panel) signs in by sending a one-time code to the bot, so it shares the Telegram account. The wallet itself is per device.

## 9. Satish AI is an app built on Satish payments, not part of the wallet

Satish AI shows what developers can build on Satish payments. It has no wallet tools, no wallet wording in its instructions, and may not import wallet code (`tests/test_ai_isolation.py`). Paying anyone is always something the person does in the wallet.

## 10. TK credits

Satish AI is paid for in TK, a usage credit that can only be spent there. 300 TK free per account; 1 sat = 5 TK; minimum 500 TK. Tasks are charged for what they use, holding at most 1,000 TK while running.

TK changes only through an append-only ledger. Each purchase gets its own Bitcoin address or Lightning invoice, settlement is a compare-and-set, and the ledger entry has a unique key, so a payment can't credit twice.

## 11. TK is paid into the operator's own Satish wallet

`XP_TK_WALLET_MNEMONIC` is the 12 words of the operator's Satish wallet. Bitcoin purchases use its addresses from index 5000 up (apart from everyday and @username addresses), and Lightning purchases use invoices from the same Lightning wallet, running on the server.

**Trade-off:** that phrase is on the server, so it should be a separate wallet with a small balance.

## 12. Satish AI delivers to Telegram, then forgets

Finished answers and files are sent to the person's Telegram chat; then the server deletes its copies. Research reads real web pages behind a wall that blocks private network addresses, and page contents are treated as untrusted data.

## 13. Satish AI has its own worker

AI tasks run on a separate worker and queue, so they never wait behind payment checks. Tasks that don't start within 3 minutes are stopped and their TK returned.

## 14. Satish for developers

API keys (`sk_test_`, `sk_live_`, stored hashed, shown once) can only create, read and cancel their owner's payment requests. Requests take sats or any currency, `metadata` and `redirect_url`. Webhooks are signed (`Satish-Signature: t=...,v1=HMAC-SHA256`), retried with backoff, and only sent to public `https` addresses.

Bitcoin goes straight to the developer's @username address pool.

## 15. Developer Lightning: Satish receives, then forwards

A developer's Lightning wallet is on their phone, so the server can't see payments to it. Satish's operator Lightning wallet issues the invoice, marks the request paid at once (so the webhook fires immediately), then forwards the sats to the developer's Spark address, once per request (with a stable idempotency key), retrying up to 6 times.

**Trade-off:** Satish holds the money for a few seconds. Chosen so developers get instant webhooks. `methods: ["onchain"]` opts out.

## 16. A real demo shop

Kaduna Kicks is a separate web page with its own "server" that prices carts from its own catalogue and calls the payment request code exactly as a merchant would. It is opened from the app with a signed 4-hour pass, and orders are paid to whoever opened it.

## 17. Dev mode fails closed

Dev mode (sign-in without Telegram) is off by default and refused in staging and production.

## 18. Operator tools need a credential

`/ops` routes need `XP_OPS_OPERATOR_TOKEN`, compared in constant time, and every attempt is logged. Without it, they stay closed.

## 19. Rate limits, shared across workers

Token-bucket limits per kind of route (sign-in, money, AI, reading), keyed by the signed-in user. With Redis they are shared across workers.

## 20. Settings keep the `XP_` prefix

The project began under another name. Server settings keep the `XP_` prefix, and some internal names keep `xp`, so existing servers and databases keep working. Everything people see says Satish and TK.
