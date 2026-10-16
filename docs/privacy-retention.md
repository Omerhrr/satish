# Privacy and Retention Policy (phase 10)

What this system stores, why, how long it is kept, and what is structurally
never deleted. The enforcement code is `xp_core/jobs/retention.py` (worker
cron daily at 03:17 UTC; settings `XP_RETENTION_*`).

## Data inventory and retention windows

| Data | Where | Purpose | Retention | Enforcement |
| --- | --- | --- | --- | --- |
| Account + Telegram identity | `users`, `telegram_accounts` | identity, linkage | life of account; deletion is manual (no self-serve erase in this build - disclosed) | none automatic |
| Sessions | `sessions` | authentication | 24h TTL by design (phase 2); expired/revoked rows purged **7 days** after expiry/revocation | retention sweep |
| XP ledger entries | `xp_ledger_entries` | money trail | **NEVER auto-deleted** - append-only, reconciliaton and dispute resolution depend on it | structural (PRESERVED_SURFACES) |
| XP accounts (balances) | `xp_accounts` | balance cache over the ledger | **NEVER** auto-deleted while the user exists | structural |
| Payment intents | `payment_intents` | invoice/settlement records | **NEVER** auto-deleted (financial record) | structural |
| Task budgets/ledger refs | `tasks` | service delivery + audit | life of account | none automatic |
| Task events | `task_events` | agent execution evidence | **NEVER** (append-only evidence trail) | structural |
| Audit events | `audit_events` | security/business trail | **NEVER** (evidence trail) | structural |
| Artifacts (PDFs, research deliverables) | artifact store + `artifacts` | user deliverables | until explicit user delete or account closure; **never** swept automatically (deleting a paid deliverable silently would be a trust violation) | user action only |
| Research sources | `research_sources` | provenance/citations | retained while the task exists (citations must remain resolvable) | none automatic |
| Notifications | `notifications` | condition alerts to the user | read: **30 days**; unread: **90 days** (an unrelayed notification must not silently vanish while it might still be delivered) | retention sweep |
| Automation runs | `automation_runs` | run history | finished runs: **180 days**; running rows never swept | retention sweep |
| Email drafts | `email_drafts` | preview-before-send content | terminal drafts (sent/failed/refused/unknown_outcome): **30 days**; `drafted` drafts are never swept (user content pending a decision) | retention sweep |
| Service credentials | `service_credentials` | encrypted (Fernet) external connection credentials | until user disconnects (hard delete) | connection revocation |

## What this policy does NOT do (honest boundaries)

- No self-serve "delete my account" flow exists yet; account closure with
  full data erasure is a manual, human-coordinated process that must
  explicitly reconcile the immutable ledger before anonymizing identity
  rows (KL-10).
- The Telegram relay is implemented (KL-06 closed): every notification gets
  exactly ONE push decision, so retention windows above were chosen so
  nothing unread expires before delivery could plausibly happen (the 24h
  relay lookback is comfortably inside the 90-day unread window); unknown
  and refused outcomes are terminal rows, never silent loops.
- Backups inherit retention: a restore (R5) resurrects data deleted after
  the backup was taken. Backup snapshots are outside the sweep's reach by
  design - restore verification, not retention, governs them.

## Verification

`tests/test_phase10_ops.py::test_retention_sweep_deletes_only_within_windows`
pins the exact deletion matrix, and `retention_proof()` (used by the backup
drill) demonstrates the preserved surfaces survive any sweep.
