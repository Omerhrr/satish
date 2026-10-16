# Incident Response Playbooks (phase 10)

Operational runbooks for the failure modes this system can actually enter.
Each runbook follows the same shape: **detect** (which signal fires),
**triage** (what to check first), **contain**, **recover**, **postmortem**.
The guiding rule is the project's honesty principle: never fabricate a
recovery that did not happen, and never auto-repeat consequential actions.

## Severity ladder

| Sev | Definition | Examples | Response |
| --- | --- | --- | --- |
| S1 | Money integrity at risk or user funds unreachable | balance drift alert, double-credit alert, wallet/Lightning outage mid-payment | immediate; freeze agent task creation if needed |
| S2 | Feature outage with workaround | research/commerce/email degraded, worker queue stuck | same business day |
| S3 | Degradation without user impact | rate-limit noise, single job retries | backlog |

Detection surfaces: `/api/v1/ops/reconciliation/alerts` (operator queue),
`/api/v1/ops/observability` (counts + policy echo), `/api/v1/health`
(component status), worker cron logs (`xp_reconciliation_complete`,
`retention_sweep_complete`), API structured logs (`rate_limit_tripped`,
`request_id` correlated).

---

## R1 — Payment discrepancy (balance/alert)

**Detect**: open `balance_mismatch` / `purchase_credited_more_than_once` /
`purchase_entry_without_settled_intent` critical alert in /ops; or
`xp_reconciliation_complete ok=false` in worker logs.

**Triage**: read the alert's `expected` vs `observed` (ledger sum vs account
row — the ledger is authoritative by design). Pull the user's
`GET /api/v1/xp/ledger` and the payment intent trail. Establish which side
is wrong: a wrong balance row (repairable) vs a wrong ledger entry
(append-only — needs a corrective `adjust` entry, never a rewrite).

**Contain**: if credits may be duplicated, suspend new agent task creation
for the affected user (task budget reservations consume XP) and stop
`purchase` settlement by pausing the worker's reconciliation/settle path —
NOT by editing ledger rows.

**Recover**: repair the account row to equal the ledger sum (or append an
`adjust` entry if the ledger itself is wrong, with a reason string). Re-run
reconciliation (`POST /api/v1/xp/reconcile` in dev, worker schedule in
prod). Resolve the alert via `POST /ops/reconciliation/alerts/{id}/resolve`
with a note describing the actual repair.

**Postmortem**: audit_events carry the full trail (`xp.reconciliation_flag`,
the repair adjust). Record the root cause in docs/known-limitations.md if it
reveals a structural gap.

## R2 — Ledger/job queue stuck (worker down)

**Detect**: `/health` queue component `not_configured`/error; reconciliation
timestamps in observability going stale; receipts/agent jobs never
finishing.

**Triage**: check Redis connectivity (XP_REDIS_URL), worker process logs,
and whether the cron heartbeat fired. Distinguish worker-down from
queue-poisoning (one job crashing repeatedly — job_timeout=300s bounds it).

**Contain**: restart the worker. A poisoned job is identified by its
repeated error in automation_runs/task_events; fix code, do not hand-edit
rows.

**Recover**: jobs are idempotent by design (ledger idempotency keys,
receipt dedupe); re-running the sweep is safe. Verify with a manual
reconcile.

## R3 — Lightning node unavailable / uncertain payment

**Detect**: `/health` lightning component; payment stuck `in_flight`;
`unknown_outcome` disclosures from the adapter.

**Triage**: the adapter's taxonomy is authoritative: `failed` (definitively
not paid — safe to refund/release), `unknown_outcome` (MUST NOT be treated
as paid or unpaid until the node answers). Check lnd reachability (ping,
grpc), channel liquidity via `/lightning/health`.

**Contain**: stop initiating payments while the node is unreachable; the
state machine refuses `authorized -> in_flight` transitions without the
node anyway.

**Recover**: on reconnect, re-query in-flight payments to resolution before
any settle/release decision. SCB channel recovery follows
`scripts/lnd_regtest_drill.py` stages 7-8 on a healthy host.

**Postmortem**: any `unknown_outcome` that later resolved either way must be
reconciled against the payment intent row; document timing.

## R4 — Credential compromise (bot token, vault key, session)

**Detect**: unexpected sessions (`GET /api/v1/auth/sessions` last_used_at
heartbeat), audit_events showing foreign access, operator-side alerts.

**Triage**: identify scope: one session (revoke per-session), one user
(revoke all + rotate), or operator secret (vault key / bot token).

**Contain**: revoke affected sessions server-side (24h TTL bounds exposure
by design); rotate the Telegram bot token via BotFather; if the vault key
leaked, rotate `XP_CONNECTIONS_CREDENTIAL_KEY` — note stored credentials
must then be re-linked by users (Fernet cannot be migrated without the old
key).

**Recover**: users re-launch the Mini App (fresh initData exchange). Verify
via sessions list.

## R5 — Data loss / restore (database or artifacts)

**Detect**: unavailable DB, corrupted volume, accidental deletion.

**Triage**: establish the latest good backup (pg_dump schedule; artifact
directory snapshot) and the exact loss window. The backup drill
(`make backup-drill`) defines the verification gates you will re-run.

**Contain**: stop writes (API maintenance mode) before restoring to avoid
split-brain.

**Recover**: restore Postgres via pg_restore; restore artifact bytes;
re-run the drill's verification gates against the restored instance: row
counts, `reconcile_all` ok, settled-intent 1:1, artifact digests. The
Lightning channel state recovers from SCB per R3/drill — a seed phrase
alone never restores channels (documented limitation).

## R6 — Abuse / rate-limit event

**Detect**: `rate_limit_tripped` log spikes from one subject; 429 ratio in
observability.

**Triage**: subject = IP + bearer fingerprint. Correlate the request_id
values in logs to identify targeted endpoints (auth stuffing vs scraping).

**Contain**: block at the edge (reverse proxy) for the IP; revoke sessions
if a specific bearer is abusive (R4).

**Recover**: no data repair needed; verify bucket behavior returns to
normal. If limits themselves are wrong (legit users tripped), tune
`xp_core/services/ratelimit.py` RULES — changes are code-reviewed and
tested, not hot-patched.

## Ops access reality (honest disclosure)

`/ops/*` endpoints are DEV_MODE-gated in this build. Production operation
requires putting an operator access control (VPN, mTLS, or an admin
authenticator) in front of them before disabling that gate — see
docs/security-review.md F-03.
