# Known Limitations Register (phase 10)

The single consolidated register of everything this build honestly cannot
do yet. Each item: what is missing, the impact, and where the re-open
instrument lives. Phase docs keep their local context; this register is the
release-facing rollup (plan phase-11: "Open issues and known limitations").

| ID | Limitation | Impact | Instrument / path to close |
| --- | --- | --- | --- |
| KL-01 | DSH live verification has never run: no DeepSeek API key is configured | The pinned-revision client is contract-tested offline (53 tests) but the live round trip (real completions, real usage numbers) is unproven | `make dsh-verify` the moment a key exists (docs/dsh-integration.md) |
| KL-02 | Lightning live drill needs a healthy host (zmq, bitcoind regtest, two lnd nodes) | Invoice/payment/recovery state machines are lnd-identical by construction and unit-tested, but the 8-stage live drill has not executed here | `make lightning-drill` (docs/lightning-integration.md) |
| KL-03 | btcwallet stall limitation in lnd recovery path | Documented upstream behavior affecting channel-force-close timing; disclosed, not worked around | docs/lightning-integration.md open items |
| KL-04 | Production Postgres backup/restore (pg_dump/pg_restore) not exercised here | The drill proves the logical roundtrip + verification gates on SQLite; operator must run the same gates after a real pg_restore | docs/incident-response.md R5 |
| KL-05 | Lightning SCB restore needs a live node host | SCB roundtrip is code-verified; the physical restore rehearsal awaits the drill host | `make lightning-drill` stages 7-8 |
| KL-06 | **CLOSED** - Telegram notification relay is implemented (one push decision per notification: sent / refused / unknown / skipped, never auto-retried). Residual: live `bot_api` delivery awaits a real bot token + chat; canned mode proves the full path | none remaining in code; live-mode evidence pending | `docs/email-automation.md` relay section, `tests/test_relay.py` |
| KL-07 | Live search/fetch providers: canned only | web.search is canned forever-honest; web.fetch http mode is built + walled but not enabled without operator config | XP_RESEARCH_FETCH_MODE=http with eval re-run (`make research-eval`) |
| KL-08 | Commerce ad-library integration is canned fixtures | Scoring/comparison logic is real; the live ad-library connector does not exist | docs/commerce-intelligence.md |
| KL-09 | Rate limiting is in-memory per API process; subject keyed on presented bearer + IP | Multi-worker deployments under-limit by worker count; bearer-rotation gets fresh buckets | Redis-backed RateLimiter (same interface) before multi-worker prod; validation-joined per-user keys |
| KL-10 | **CLOSED** - self-serve data export + ledger-aware account closure implemented (typed confirmation, precondition refusals, clean-reconciliation gate, identity anonymization, money/evidence trail retained). Residual: operator-assisted paths for nonzero-balance closure are contact-based | residual only affects users who close with a balance | `docs/privacy-retention.md` closure section, `xp_core.services.closure`, `tests/test_account.py` |
| KL-11 | `/ops/*` surfaces are DEV_MODE-gated only | Production operator access needs real access control (VPN/mTLS/admin auth) in front before opening | docs/security-review.md F-03 |
| KL-12 | Expiring signed URLs for artifacts (S3 era) | Local storage uses owner-checked direct download; S3 backend needs signed-URL expiry | storage backend upgrade |
| KL-13 | initData replay-window tuning + per-tool output size caps | Threat-model open items carried since phase 2/6; bounded by 24h session TTL and tool caps today | docs/threat-model.md |
| KL-14 | CI workflows remain parked on `backup-with-ci` | The GitHub token used for pushes lacked `workflow` scope; `.github/` is off main until a scoped token merges it | `git merge backup-with-ci` + push with a workflow-scoped token |
| KL-15 | Independent external security review not performed | Phase-10 review is internal and structured but not independent; required before real-value production use | docs/security-review.md |

Anything claiming production readiness must first clear: KL-01 (agent
claims), KL-02/KL-04/KL-05 (money claims), KL-09 (abuse surface),
KL-15 (release gate).
