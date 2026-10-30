# Satish: a self-custodial Bitcoin wallet and payments platform for Africa, starting in Telegram

*Proposal for Btrust, prepared for the Btrust Build-A-thon at DevFest Kaduna 2026.*

## 1. Why Btrust

Btrust funds Bitcoin development with a focus on developers in Africa and India, and trains African Bitcoin and Lightning engineers through the Btrust Builders Programme. Satish is built in Kaduna, is fully open source (MIT), and is aimed at the people Btrust exists to reach: everyday Nigerians, and the developers who build for them.

## 2. The problem

- **Holding bitcoin is hard for most people.** Wallets feel technical, addresses are long, and the easy option is to leave money on an exchange, which isn't really owning it.
- **Paying with bitcoin is harder.** Fees make small payments costly, and few shops or apps accept it.
- **For developers, taking bitcoin is a project in itself.** Running nodes, watching addresses and handling Lightning is too much for a small business or a student's app.

Meanwhile, Telegram is already part of daily life for millions of Nigerians.

## 3. What Satish is

### A wallet people actually own

A Bitcoin and Lightning wallet inside Telegram, and in the browser as an extension. The 12-word recovery phrase is made on the person's phone and never leaves it; the server cannot move anyone's money.

- **Pay people, not addresses:** `@ada`, with every payment checked by the payer's phone so a server can't redirect it.
- **Lightning for everyday spending** (Breez SDK on Spark), from the same 12 words: ₦500 arrives in seconds for almost nothing.
- **Money in local terms:** type amounts in naira or any currency, in 12 languages including Hausa, Yoruba, Igbo and Pidgin.
- **Social features where people already are:** payment links for WhatsApp, `/split` and `/pay` in Telegram groups.
- **Safe on bad days:** encrypted Telegram backup, recovery with trusted people (any 2 of 3), a daily spending limit against scams, fixing stuck payments, and an easy way to leave with all your money.

### Payments any app can use

**Satish for developers** lets any website, app or bot take Bitcoin and Lightning with one API call and a signed webhook. Bitcoin goes straight to the developer's own wallet; Lightning is forwarded to it within seconds. The **Kaduna Kicks** demo shop shows a complete checkout in a normal browser.

### Satish AI: the first app built on Satish payments

To prove the platform, we built an app on it: **Satish AI**, a research assistant people pay for in bitcoin. It does web research with sources, comparisons, reports with charts, and automations, in the user's language. It runs on TK credits paid by Lightning or Bitcoin into the operator's own Satish wallet, exactly as any developer's app would take payment. It is kept completely separate from people's wallets.

## 4. How it stays trustworthy

- **Self-custody by design:** keys only on the device, encrypted with the person's password; the server has no key, no xpub and no balances.
- **Payments can't be redirected:** every @username address is signed by the recipient's wallet and checked by the payer's phone.
- **Credits are counted exactly once:** an append-only ledger, each payment credited once, and automatic reconciliation.
- **Open about the gaps:** [known-limitations.md](known-limitations.md) lists everything not finished, including that there hasn't been an independent security review yet.

## 5. Evidence you can check

| What | Where |
|---|---|
| 370+ server tests | `make test` |
| 50+ wallet tests, including official BIP84 test vectors | `cd apps/web && bun test tests` |
| End-to-end server run, no outside services | `make demo` |
| Live app on the test network | the Satish bot on Telegram, `satish.rogan.live` |
| Demo shop | Wallet > Settings > Developers > See it on a real shop website |

## 6. What support would let us do next

1. **An independent security review** of the wallet and payment code, so people can trust it with real savings.
2. **Payments that never touch Satish, even for seconds,** so developers get instant Lightning payments with no middleman.
3. **Developer tools:** client libraries and plugins for WooCommerce and Shopify, so Nigerian shops can accept bitcoin in an afternoon.
4. **Our own Bitcoin data server**, for privacy and reliability.
5. **Native-speaker review** of the Nigerian languages, and more African languages.
6. **Contributors** through Btrust Builders: good first issues in the wallet, the developer API and translations.

## 7. Open source and maintenance

MIT licensed, one repository, every feature covered by tests and documented decisions ([decisions.md](decisions.md)). Security reports through [SECURITY.md](../SECURITY.md). Maintainer: @Omerhrr; how to contribute: [CONTRIBUTING.md](../CONTRIBUTING.md).
