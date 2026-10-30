# Security policy

Satish is a wallet. People keep real money in it, so we take reports seriously and answer them quickly.

## Reporting a problem

**Please don't open a public issue for anything that could be used to steal money or data.**

Report it privately instead, by either:

- opening a [GitHub security advisory](https://github.com/Omerhrr/satish/security/advisories/new) on this repository, or
- messaging the maintainer, @Omerhrr, on GitHub.

Please include:

- what is affected (a screen, an API route, a file);
- steps to reproduce it, or a proof of concept;
- the commit or version you tested.

Use the test network (testnet4 for Bitcoin, regtest for Lightning) when you test. You should never need real money to show a problem.

## What's in scope

Everything in this repository, in particular:

- **the wallet** on the device: keys, encryption, signing, backup, social recovery, private-key sweep (`apps/web/app/lib`);
- **@usernames and payment requests**, including the signed address pools that stop a server from swapping in its own address;
- **Lightning**: the in-app Breez wallet, and the server's operator wallet that receives TK and developer Lightning payments;
- **the developer API**: API keys, payment requests, webhook signing, the demo shop;
- **sign-in**: Telegram login, sessions, linking the browser extension;
- **Satish AI** and TK credits, including the wall that keeps the AI away from wallets;
- **the bot, the browser extension and the server**.

Out of scope: problems in Telegram itself, GitHub, or third-party services we use (mempool.space, Breez and Spark, DeepSeek, Brave Search, Onramper). Please report those to them; if they affect Satish users, tell us too.

## What we promise

- We reply within **3 days** and keep you updated.
- We aim to fix serious problems within **30 days**, and publish the details at most **90 days** after your report, agreed with you. Sooner if it's being actively exploited.
- We won't take legal action against good-faith research that respects users' data and never touches money that isn't yours.
- With your permission, we credit you in the fix.

## Where things stand today

Being honest about this matters more than looking finished:

- Satish has **not had an independent security review yet**. Until it has, the app suggests keeping only spending money in it on mainnet.
- Lightning payments made through a developer's payment request pass through Satish's operator wallet for a few seconds before being forwarded. TK payments by Lightning go to an operator wallet whose phrase is on the server. Both are explained in [docs/threat-model.md](docs/threat-model.md).
- The full list of open gaps is in [docs/known-limitations.md](docs/known-limitations.md).
