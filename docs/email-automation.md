# Email & Automation Workflows (phase 9)

External actions are the most dangerous surface an agent has: a wrong email
or a runaway scheduled job costs real trust. This phase's design therefore
front-loads the limits - preview before send, approvals bound to content
and time, encrypted revocable credentials, hard XP budgets, and run history
that records every attempt including the ones that did nothing.

## Surfaces

| Surface | Endpoint / tool | Notes |
|---------|-----------------|-------|
| Link service | `POST /connections` | provider allowlist (`smtp`), scopes intersected with the provider spec, credential encrypted at rest |
| List / revoke | `GET/DELETE /connections` | revocation hard-deletes the credential row; never returns secrets |
| Providers | `GET /connections/providers` | published capability surface |
| Drafts | `GET /drafts`, `GET /drafts/{id}` | owner-checked preview; read-only by design |
| Jobs | `POST/GET /jobs`, `GET /jobs/{id}` | direct user creation needs no approval (the user is the actor) |
| Lifecycle | `POST /jobs/{id}/pause\|resume\|cancel` | resume recomputes `next_run_at`; cancel is terminal |
| Run history | `GET /jobs/{id}/runs` | every attempt with status, XP, error |
| Manual run | `POST /jobs/{id}/run` | SAME `process_job` code path as the sweep - never a bypass |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` | persisted + relayed to Telegram by the worker (KL-06); `relay_status` discloses the one push decision |
| Agent tools | `email.draft`, `email.send`, `automation.schedule` | scope wall + approval gate stack (`email:send`, `automation:write` in USER_TASK_SCOPES) |

## Trust flow for email

```
email.draft  -> EmailDraft row (content digest) + email.drafted event
             -> user previews in the Mini App (GET /drafts/{id})
email.send   -> scope wall (email:send granted) -> approval gate
             -> Approval(action_digest = sha256(tool + exact content),
                         expires_at = now + TTL)
             -> USER decision (approve/deny; expiry enforced at decision)
             -> resume -> handler: unsent draft match + linked connection
             -> provider send (canned | smtp) -> sent | failed | unknown_outcome
```

- The approval digest wraps the EXACT `{to, subject, body}` - what you
  approve is what gets sent, byte-for-byte.
- A sent draft can never be sent again; a resend needs a new draft (new
  digest) and a new approval.
- Refusals (no connection, credential error) do NOT consume the draft -
  link a service and retry with a fresh approval.

## Outcome taxonomy (honest uncertainty)

| Outcome | Meaning | System behavior |
|---------|---------|-----------------|
| `sent` | server accepted the message | draft `sent`, `email.sent` event |
| `refused` | definite rejection (auth, recipient, DATA) | draft `failed`; safe to retry with a new approval |
| `unknown` | transport failed mid-session; server MAY have accepted | draft `unknown_outcome`, loud disclosure, **never auto-retried** |

The SMTP provider (stdlib `smtplib` off-loop) maps
auth/sender/recipient/DATA refusals to `refused` and timeouts/EOFs/OSErrors
to `unknown`. Tests prove both against a local asyncio loopback SMTP server
(delivery + recipient-refusal + mid-session vanishing).

## Credential vault

- Fernet ciphertext in `service_credentials`; key = sha256(master) - the
  master key is never stored. `XP_CONNECTIONS_CREDENTIAL_KEY` in non-dev.
- Dev fallback key is a documented constant, used only in dev mode and
  DISCLOSED on every connection response.
- `load_credential` is the only decryption path; revoked connections never
  decrypt (row is hard-deleted at revocation).

## Automation scheduler

```
run_due_jobs (worker cron, XP_AUTOMATION_SWEEP_INTERVAL_SECONDS)
  for each active, due job: process_job(...)
    1. stale "running" run -> mark failed (crash recovery) / else wait
    2. last run blocked_on_approval -> pending: WAIT (no repeat, no spam)
                                       denied: fail task, release, run failed
                                       approved: resume the SAME task
    3. total budget exhausted -> skipped_total_budget + auto-pause + notify
    4. balance pre-check -> skipped_budget (clean, no ledger touch)
    5. spawn Task(budget = min(per_run, remaining_total)) + reserve
       (idempotency key automation:{job_id}:{run_number}) -> execute
       -> finalize: run status, XP bookkeeping, conditions -> notifications,
          consecutive-failure ladder -> auto-pause + notify
```

- Schedules: `every <n><s|m|h|d>` (>= 60s), `daily HH:MM` (UTC), `hourly`,
  `daily`. Anything else is refused loudly - no silent cron guessing.
- Conditions (whitelist-validated, unknown keys refused):
  `{"notify_on": ["run_succeeded"|"run_failed"], "balance_below_xp": N}`.
- Budgets are operator-capped (`XP_AUTOMATION_MAX_BUDGET_*`) and enforced
  by the ledger itself: settlement beyond a task budget is refused, so a
  greedy plan cannot exceed `min(per_run, remaining_total)`.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `XP_CONNECTIONS_CREDENTIAL_KEY` | - (dev fallback) | vault master key |
| `XP_EMAIL_SEND_MODE` | `canned` | `canned` \| `smtp` |
| `XP_APPROVAL_TTL_MINUTES` | `60` | approval expiry window |
| `XP_AUTOMATION_SWEEP_INTERVAL_SECONDS` | `60` | worker sweep cadence |
| `XP_AUTOMATION_RUN_STALE_SECONDS` | `3600` | crash-recovery window |
| `XP_AUTOMATION_MAX_CONSECUTIVE_FAILURES` | `3` | auto-pause ladder |
| `XP_AUTOMATION_MAX_BUDGET_PER_RUN_XP` | `10000` | operator cap |
| `XP_AUTOMATION_MAX_BUDGET_TOTAL_XP` | `100000` | operator cap |
| `XP_TELEGRAM_RELAY_MODE` | `canned` | `canned` \| `bot_api` (bot_api requires `XP_TELEGRAM_BOT_TOKEN`) |
| `XP_TELEGRAM_RELAY_LOOKBACK_HOURS` | `24` | unread notifications older than this are skipped as stale |
| `XP_RELAY_SWEEP_INTERVAL_SECONDS` | `60` | worker relay cadence |

## Notification relay (KL-06)

A worker cron sweep gives every notification EXACTLY ONE push decision,
recorded in `relay_status` + `relay_detail` + `relayed_at`:

- `sent` - the provider accepted the message (Bot API returned `ok: true`);
- `refused` - Telegram definitively refused (blocked bot, chat not found,
  bad token). Refusals are terminal; retrying one would only spam;
- `unknown` - timeout, transport error, or 5xx: the send MIGHT have
  completed. The row records the never-auto-retry disclosure; nothing is
  silently re-sent;
- `skipped` - the relay deliberately did not attempt: read in-app before
  the push, no linked Telegram account, or past the 24h lookback window.

`XP_TELEGRAM_RELAY_MODE=canned` (default) proves the full path offline;
every canned receipt states plainly that nothing was transmitted.
`bot_api` is the same code path with the real Bot API behind it, and it
refuses to construct without a configured bot token - the system never
silently downgrades a requested real send to canned.

## Honest open items

- Live relay delivery needs a real bot token plus a real chat (the bot_api
  provider path is transport-tested offline); canned mode proves the sweep
  and disclosure path deterministically.
- Live SMTP delivery needs a real server and an operator master key; the
  provider path is proven offline against a loopback server.
- Full cron expressions (5-field, timezone-aware) are deliberately not
  implemented; the documented grammar subset keeps scheduling
  deterministic and testable.
- The manual `POST /jobs/{id}/run` executes inline in dev (no Redis); with
  Redis configured the scheduled sweep runs on the worker while manual
  triggers remain inline - long-running runs therefore block that HTTP
  request, which the endpoint discloses by returning the final run row.
