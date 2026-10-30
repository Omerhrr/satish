# Threat model

What we protect, who might attack it, and how Satish stops them. Open gaps are in [known-limitations.md](known-limitations.md).

## What we protect

| | Where it lives |
|---|---|
| Recovery phrases and private keys | only on the person's device, encrypted with their password |
| People's bitcoin and Lightning funds | controlled only by those keys |
| Who pays whom (@username payments, requests) | server database; balances and other activity are never sent |
| TK balances | server ledger, append-only |
| Developer API keys and webhook secrets | server; API keys stored only as hashes |
| The operator's Lightning wallet | server; receives TK and developer Lightning payments |
| Satish AI conversations and files | server until delivered to Telegram, then deleted |
| Sessions | server stores only hashes |

## Threats and what stops them

**A hacked or dishonest Satish server tries to steal money.**
The server has no keys, so it can't spend. It could try to give out its own address for an @username payment. It can't, because every address is signed by the recipient's wallet identity key, and the payer's phone checks the signature and remembers the key from the first payment. The same applies to Lightning addresses.

**A hacked server tries to steal from the operator wallet.**
This is possible: the operator's Lightning phrase is on the server. That is why the operator should keep only a small amount there and move income out regularly. Developer Lightning payments sit there only for the seconds before they are forwarded.

**Someone gets the person's phone.**
The phrase is encrypted with their password (PBKDF2, 310,000 rounds, then AES-256-GCM). The optional app lock asks for the password on opening and after 5 minutes away. Showing the phrase or exporting keys always asks again.

**The person is tricked into paying the wrong place.**
A full review before every payment; an extra "I've checked" step for new addresses, large amounts and high fees; and a daily limit that makes big payments wait 30 seconds, which stops panic payments to scammers.

**Losing the phone or the password.**
The 12 words restore everything. The encrypted Telegram backup and social recovery (any 2 of 3 trusted people) are optional extras. One piece of a social recovery split reveals nothing.

**Fake sign-in.**
Telegram's login data is checked with the bot token and must be recent. Extension sign-in uses a one-time code sent to the bot from the person's own Telegram.

**Satish AI is manipulated by a web page.**
Pages the AI reads are marked as untrusted data, not instructions. The AI has no wallet tools at all, so the worst a manipulated AI could do is give a bad answer or draft a bad email, and emails are only sent after the person approves that exact text. Web fetching blocks private and local network addresses, odd ports and oversized responses.

**Paying for TK twice, or being credited twice.**
Each purchase has its own address or invoice. Settling is a compare-and-set, and the ledger entry has a unique key, so replays can't credit twice. Reconciliation compares balances with the ledger and raises alerts.

**A developer's key leaks.**
It can only create and read that developer's payment requests: it can't see balances or move money. Keys can be revoked in the app.

**Fake webhooks, or webhooks used to attack internal systems.**
Webhooks are signed with HMAC and include a timestamp. Endpoint addresses must be `https` on public IPs, checked again before every delivery.

**A forged demo shop link.**
The shop's pass is signed and expires after 4 hours.

**Too many requests.**
Rate limits per kind of route (sign-in, money, AI, reading), with a Redis-backed option for several workers.

**Privacy leaks.**
Chain data comes from mempool.space by default, which can see which addresses a wallet looks up. Running your own Esplora server fixes that (`NUXT_PUBLIC_ESPLORA_URL`). Logs carry IDs, never keys or message content.

## Still open

- No independent security review yet.
- The operator wallet's phrase is on the server (see above).
- Spark's operators are part of the Lightning trust model: they can't take funds, but they are not as trust-free as plain Bitcoin.
