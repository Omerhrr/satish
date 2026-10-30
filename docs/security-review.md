# Security review

This is an **internal** review, done while building Satish. It is not a substitute for an independent audit, which hasn't happened yet ([known-limitations.md](known-limitations.md)).

## How we check

1. Walk every trust boundary in the [threat model](threat-model.md).
2. For each security claim, find the test that proves it. A claim without a test counts as a finding.
3. Re-run the full test suites before each release: server (`make test`) and wallet (`cd apps/web && bun test tests`).

## What has been checked, and the tests behind it

| Area | What we check | Tests |
|---|---|---|
| Keys stay on the device | official BIP84 test vectors; the phrase is encrypted at rest; the signer refuses coins that aren't the wallet's and fees that differ from the review | `apps/web/tests/wallet-core.test.ts` |
| Backup and recovery | the Telegram backup is unreadable without the password; Shamir pieces rebuild only with 2 of 3, and wrong pieces are caught | `cloud-backup.test.ts`, `shamir.test.ts` |
| @username payments can't be redirected | address pools must be signed by the identity key; Lightning addresses too | `tests/test_handles.py`, `spark-sign.test.ts` |
| TK credits exactly once | replaying a settlement doesn't credit again; the ledger matches balances | `tests/test_xp_economy.py`, `tests/test_tk_payments.py` |
| Satish AI can't reach wallets | no wallet imports, tools or prompt text | `tests/test_ai_isolation.py` |
| AI web fetching | private IPs, odd ports, redirects to local addresses and huge pages are refused | `tests/test_research.py` |
| Developer API | keys are hashed and shown once; keys only reach their owner's requests; webhooks are signed; webhook URLs must be public `https`; Lightning forwarding happens once per request | `tests/test_developers.py` |
| Demo shop | forged or expired passes are refused; prices come from the server | `tests/test_demo_shop.py` |
| Sign-in | tampered, stale or wrong-bot Telegram data is refused; sessions expire and can be revoked | `tests/test_telegram_auth.py` |
| Abuse | rate limits per kind of route, shared across workers with Redis | `tests/test_ratelimit_redis.py` |
| Operator tools | `/ops` needs a configured credential; every attempt is logged | `tests/test_ops_identity.py` |

## Findings

| | Finding | Status |
|---|---|---|
| 1 | An early version kept the wallet on the server, which needed the phrase to sign | **Fixed**: the wallet moved onto the device; the server wallet was removed |
| 2 | No rate limiting | **Fixed** |
| 3 | Operator tools protected only by the dev-mode flag | **Fixed**: a credential is required, and access is logged |
| 4 | Dev mode could be switched on in production | **Fixed**: it is refused when the environment is staging or production |
| 5 | Lightning sends to a Bitcoin address failed with an idempotency key | **Fixed**: those sends don't use one, and the app checks history before allowing a retry |
| 6 | The operator Lightning wallet's phrase is on the server | **Accepted, disclosed**: keep a small balance there |
| 7 | Developer Lightning payments are held for seconds before forwarding | **Accepted, disclosed**: chosen so webhooks work instantly |

No critical findings are open. Please report anything new through [SECURITY.md](../SECURITY.md).
