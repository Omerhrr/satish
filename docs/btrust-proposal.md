# XP: a self-custodial Bitcoin wallet that pays for AI work, inside Telegram

*Proposal for Btrust, prepared for the Btrust Build-A-thon at DevFest Kaduna City '26.*

## 1. Why Btrust

Btrust was set up by Jack Dorsey and Jay-Z, seeded with 500 BTC, to fund
Bitcoin development with a focus on developers in Africa and India, mainly
through grants. Through the Btrust Builders Programme it trains African Bitcoin
and Lightning engineers. XP is built in Kaduna by African developers, it is
fully open source (MIT), and it is aimed at the users Btrust exists to reach.

## 2. The problem

For most Nigerians, Telegram is already part of daily life, and AI tools are
becoming useful for work: research, comparing prices and suppliers, writing
documents. But paying for them means a foreign card, a subscription and a
custodial account, and the cards often fail. Meanwhile, the people who already
hold bitcoin are asked to hand it to an exchange or app before they can use it.

## 3. What XP is

A Telegram bot and Mini App with two halves that work together:

- **A real, self-custodial Bitcoin wallet.** The 12-word recovery phrase is
  created on the user's phone and never leaves it; the XP server has no wallet
  endpoints at all. Users can receive (QR), send (with fee choice and a full
  review), keep an address book of named contacts, buy bitcoin with naira
  through licensed partners that deliver straight to their own address, see
  values in naira, and back the wallet up to their own Telegram, encrypted
  with their password.
- **An AI assistant you pay with bitcoin.** Users buy XP credits in sats,
  paid in one tap from the in-app wallet to the operator's own wallet, then
  ask for research, comparisons and PDF reports with sources. Every task has
  a budget the user approves; unused XP comes back; anything consequential
  (like sending an email) waits for the user's OK.

The full loop, all in Telegram: **buy sats → pay for work → get the report**,
without anyone taking custody of the user's money.

## 4. How it stays honest about money

- **Self-custody is structural:** keys only on the device; phrase encrypted at
  rest (PBKDF2-SHA256 + AES-256-GCM); the AI agent is not in the signing path.
- **The operator never holds user funds either:** XP payments go to a
  watch-only address derived from the operator's public key; the server can
  watch but never spend.
- **XP is credited exactly once:** each payment is checked on-chain, a
  compare-and-set marks it settled, and the ledger entry is keyed per payment,
  so replays and duplicate checks cannot double-credit. The XP ledger is
  append-only and reconciled against payments.
- **No silent failure modes:** dev shortcuts are off by default and refused in
  production; operator tools need a credential and are audited.

## 5. Evidence a reviewer can run

| What | Where |
|---|---|
| ~300 server tests (ledger, payments, auth, security walls) | `make test` |
| Wallet tests: official BIP84 vectors, signing, coin selection, backup | `cd apps/web && bun test tests` |
| End-to-end demo with no external services | `make demo` |
| Live deployment | Telegram Mini App at `satish.rogan.live` (testnet4) |

Known gaps are listed openly in `docs/known-limitations.md` (for example:
no independent security review yet, Lightning still uses the demo provider).

## 6. What support would let us do next

1. **Independent security review** of the wallet and payment code before real
   money at scale.
2. **Lightning for small payments** (an lnd node), so a ₦500 task doesn't pay
   an on-chain fee.
3. **Our own Esplora/mempool server** so wallet lookups don't depend on a
   third party (better privacy).
4. **Local-first AI tasks** built with Nigerian users: market prices,
   supplier comparison, document drafting in English, Hausa, Yoruba and Igbo.
5. **Contributor onboarding** through the Btrust Builders community, with
   good-first-issues in the wallet and the AI tools.

## 7. Open source and maintenance

MIT licensed, single repository, every feature covered by tests and
documented decisions (`docs/decisions.md`). Security reports through
`SECURITY.md`. Maintainer: @Omerhrr; module owners in `CONTRIBUTING.md`.
