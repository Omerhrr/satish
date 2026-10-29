# Decision Log

Living record of architecture decisions and their status. Format follows the
plan's guidance: document the decision, the trigger for revisit, and the
honest current state.

## D1 - Python workspace packaging: `packages/py-core`

**Decision:** introduce a shared internal Python package (`xp-core`) for
settings, logging, DB base, models, ledger engine, and storage backends.

**Why:** the plan's `packages/` lists only TS packages, but api/worker/bot all
need the same models and ledger invariants; duplicating them would drift.
The plan itself defers exact packaging to an integration spike.

**Revisit when:** the queue-technology prototype (PostgreSQL-backed vs Redis)
settles the deployment story.

## D2 - SQLite as the zero-dependency local database

**Decision:** `XP_DATABASE_URL` defaults to SQLite (aiosqlite) locally;
Postgres is the target for regtest+ environments via docker-compose.

**Why:** phase 1 acceptance says a developer starts the system from docs with
no production secrets; SQLite keeps that honest and fast. Portable column
types (String UUIDs, JSON, no dialect locks) keep migrations identical.

**Revisit when:** regtest environment work begins (phase 3).

## D3 - Queue: arq (Redis) with inline dev fallback

**Decision:** arq worker over Redis in shared environments; when Redis is not
configured the API executes the same job function inline in a thread.

**Why:** preserves the worker boundary and job semantics without forcing
infrastructure on day one. The plan explicitly defers Redis-vs-Postgres queue
to an operational prototype.

**Revisit when:** reliability tests measure retry/timeouts under load.

## D4 - Agent runtime: controlled adapter, stub-first

**Decision:** `services/agent-adapter` is the only model surface. DeepSeek is
reached via the OpenAI-compatible API; the upstream DSH integration is behind
`XP_DSH_REVISION` (currently unpinned) and tools are allowlisted/typed.

**Why:** the plan requires pinning a tested DSH revision after a spike; until
that spike, stub mode keeps CI hermetic and prevents accidental coupling.

**Revisit when:** phase-0 DSH integration spike completes (pin revision,
document lifecycle + error handling).

## D5 - Wallet & Lightning: protocols now, libraries later

**Decision:** `WalletProvider` / `LightningProvider` protocols + regtest
stubs + explicit `SigningBoundary`. No library chosen yet.

**Why:** the plan mandates a documented threat-model and integration spike
before committing to a wallet/Lightning implementation, and requires adapters
stay replaceable so the choice never leaks through the codebase.

**Revisit when:** phase-3 spikes evaluate BDK/bitcoind and LDK/CLN/lnd.

## D6 - Nuxt in SPA mode for the Mini App

**Decision:** `ssr: false` for the Mini App.

**Why:** Mini Apps run inside Telegram's webview; SSR adds auth/session
complexity with no UX benefit there. Server-side rendering can be revisited
for public marketing pages later.

## D7 - What is deliberately NOT done yet (honesty list)

- No wallet key handling of any kind (phase 3 + release gates).
- No Lightning node connectivity (phase 3+ after channel-state review).
- No real web-search provider behind `web.search` stub (phase 4).
- No payment provider settlement verification (phase 4 XP purchases).
- Dev grants exist ONLY under DEV_MODE and are audit-logged.
- ~~Telegram session revocation hardening~~ - delivered in phase 2 (short-lived sessions, server-side logout/revoke, lifecycle UI).

## D8 - DSH "upstream" = pinned DeepSeek API surface, not a package

**Decision:** the phase-0 spike found no canonical importable open-source
"DeepSeek Harness" package to pin. The upstream surface is pinned instead
via `services/agent-adapter/dsh_adapter/dsh_revision.json`: wire format
(OpenAI Chat Completions), base URL, model revisions (`deepseek-flash` /
DeepSeek-V4.1-Flash as primary, `deepseek-v4-pro` as heavy), thinking-mode
contract (disabled for planning; toggle via `extra_body.thinking.type`),
sampling-params inertness, pricing, and adapter limits. A sha256 drift gate
in `tests/test_dsh_revision.py` makes pin changes conscious; discontinued
legacy aliases (`deepseek-chat`, `deepseek-reasoner`, dead 2026-07-24) are
rejected at startup. Full contract: docs/dsh-integration.md.

**Why:** the plan requires "pin a tested upstream DSH revision" while
allowing "a separately pinned dependency, submodule, or documented
integration." Research (2026-10-15, api-docs.deepseek.com change log,
pricing, thinking-mode guide) showed the drift risk is in the API surface -
our original scaffold default `deepseek-chat` had already been discontinued
upstream. A manifest pin captures exactly the facts that can break us and
keeps the adapter the only place that knows them.

**Consequences:** re-pinning is a deliberate two-step (manifest + checksum
test) plus `make dsh-verify` live proof; no import-time coupling to any
harness package. Revisit if a canonical DSH package appears or if DeepSeek
ships an incompatible wire-format change.

## D9 - Short-lived sessions + server-side revocation model

**Decision:** bearer sessions live 24h (`XP_SESSION_TTL_HOURS`, down from 14
days), are stored as SHA-256 hashes, and all lifecycle actions are
server-authoritative: `POST /auth/logout` revokes the presented token,
`GET /auth/sessions` lists live sessions, `DELETE /auth/sessions/{id}`
revokes one by id with strict ownership (foreign ids return the same 404 as
missing ones - no oracle). A throttled `last_used_at` heartbeat (5-min
window) powers the visibility UI without write amplification.

**Why:** phase-2 acceptance demands "forged or expired payloads rejected"
and the trust boundary demands "short-lived sessions"; the Mini App
re-exchanges fresh initData on every launch, so a short TTL costs nothing
in UX. Client-side token dropping alone (the scaffold's logout) left
stolen tokens valid for weeks - unacceptable for a product whose threat
model includes Telegram-account compromise.

**Consequences:** the settings screen gains a real "Active sessions"
surface; expired/revoked tokens return 401 on every endpoint via the shared
dependency. Logout requires a bearer token even in DEV_MODE so clients
cannot mistake "cleared local copy" for "revoked server-side".

## D10 - BDK (bdkpython) for the on-chain wallet; bitcoind RPC as the chain source

**Decision:** phase-3 selects **BDK 1.x core via `bdkpython` 3.1.1** (UniFFI
Python bindings) for keys, descriptors, PSBT construction and signing, with a
**bitcoind JSON-RPC client** (`wallet_adapter/rpc.py`) as the chain source for
fee estimation, mempool probing, broadcast and confirmation tracking. The
choice was made empirically before implementation: `scripts/regtest_proof.py`
stands up bitcoind 29.0 regtest inside one process tree and proves create →
receive → balance → fee → PSBT build → sign → finalize → testmempoolaccept →
broadcast → confirmation → restore plus three failure paths (overspend,
unparseable address, cross-network address) against the real node. bdkpython
installs as a manylinux wheel (no Rust toolchain at deploy time), which
rules out the electrs-from-source path for this environment; the heavier
alternatives (full bitcoind-wallet custody, Electrum as a library) were
rejected on the plan's criteria: language binding quality, maintenance,
license (BDK: MIT/Apache-2.0-compatible), signing options, and recovery docs.

**Custody model inside this decision:**
- Persisted wallet state (per-wallet BDK sqlite under `data/wallets/`) is
  built from **public descriptors only** - tests assert the on-disk bytes
  contain no mnemonic material and no `xprv`/`tprv` strings.
- Signing happens in an **in-memory private wallet** built at unlock from the
  user's recovery phrase; the phrase lives in process memory for the unlock
  TTL (`XP_WALLET_UNLOCK_TTL_MINUTES`, default 10) and is dropped on
  lock/expiry. The persisted (public) wallet owns the UTXO graph and builds
  the PSBT; the unlocked private wallet signs it - proven by the offline
  funding tests, which run the two-wallet flow without any chain source.
- The signing boundary rejects agent actors unconditionally and binds every
  signature to an authorization digest over the reviewed transaction fields
  (destination, amount, fee, network). Validation failures do not consume the
  prepared transaction (no DoS-by-retry); only a completed signature does.
- Address aliases are labels: `prepare` resolves an alias once, the digest
  binds the resolved address, and relabeling cannot redirect an existing
  prepared transaction (tested).
- Broadcast failures are explicit: definite rejections (502) vs. node
  unreachable during send (504, "outcome unknown - resolve by txid").
- Mainnet is hard-gated in the provider constructor pending the security
  review release gate.

**Consequences:** regtest needs no electrs/esplora - chain data enters the
wallet graph via `import_transaction` (bring-your-own-chain-source), which is
also the documented seam for a full Electrum/Esplora sync later. The API
restart story is honest: `reopen()` restores graph/balance state from public
descriptors alone; signing always requires a fresh unlock. This is a
server-side signing-vault build - docs and UI must not claim non-custodial
or browser-side signing until those phases land.

## D11 - Lightning: lnd v0.21.4-beta selected via empirical drill; canned semantics provider for offline-proofable lifecycles (2026-10-15, phase 4)

**Context:** the plan requires a selected Lightning implementation, invoice
and payment lifecycles, fee preview + authorization, channel-state backup and
recovery drills, health/liquidity disclosure, and duplicate-callback-safe
accounting - with regtest integration tests for the chosen implementation.

**Decision:** lnd v0.21.4-beta, pinned and spoken to over gRPC through stubs
generated from the release's own protos (`scripts/gen_lnd_stubs.py`), same
manifest-pin philosophy as the DSH decision (D8). LDK Node was evaluated
first (binding-philosophy parity with BDK) but has no wheel in this
environment's registry; Core Lightning needs a source build with no official
prebuilt binaries here; Eclair is JVM-only. A two-node regtest drill
(`scripts/lnd_regtest_drill.py`) boots both nodes, exercises wallet init
(from captured seeds), TLS/macaroon gRPC, unlock-after-restart, and invoice
and backup RPCs, capturing version-specific API facts (v0.21.4 removed
`seed_entropy` from InitWalletRequest; the state enum is `WalletState` with
`RPC_ACTIVE`/`SERVER_ACTIVE` as ready states; the router stub is
`RouterStub`; lnd authenticates via `macaroon` metadata, not bearer tokens).

**Honest limitation (re-verified 2026-10-15):** the btcwallet
block-processor stalls on this sandbox (upstream lnd #9108/#10389/#11004
family) - on rpcpolling AND with a healthy loopback zmq probe, mined
outputs are never credited, so live channel funding cannot complete
in-sandbox. The drill reproduces cleanly: stages 1 (chain), 2 (two nodes
ACTIVE), 7 (restart + unlock) PASS; stages 3-6 and 8 report BLOCKED with
diagnostics instead of pretending. Instead of faking it, the phase ships:
(a) the real gRPC adapter, (b) a canned provider with lnd-identical
semantics (clocked expiry, preimage-bound settlement, digest-bound
authorization, checksummed SCB) that makes every lifecycle/idempotency
acceptance criterion testable offline, (c) the drill script as the re-run
instrument for a healthy host.

**Consequences:** settlement idempotency is enforced by a CAS status
transition plus the ledger's idempotency key - duplicate callbacks are
structurally incapable of double-crediting (tested with six repeats). Fee
authorization binds the digest of what was shown; wrong digest → 409.
Mainnet stays refused at provider construction (same release gate as D10).
The canned provider is disclosed verbatim in `/lightning/capabilities` -
not pretending a real node exists when it does not.

## D12 - One canonical conversion (`xp_per_sat`); receipts as derived views (2026-10-15, phase 5)

**Context:** the scaffold carried two contradictory rates (`sats_per_xp=10`
for display, `xp_per_sat=100` for actual crediting) - exactly the kind of
drift the plan's pricing_requirements ("publish the conversion") exists to
prevent. Separately, receipts could be modeled as a new table or as views.

**Decision:** `xp_per_sat` is the single published conversion; credits are
always `sats × xp_per_sat` computed at settle time. Receipts are derived
views over `(payment_intent, xp_ledger_entry)` - no receipt table - and the
PDF receipt renders from DB rows only. Reconciliation runs as a scheduled
worker job plus a dev-seam endpoint, checking (a) balance == sum(entries)
per user, (b) settled receive intents ↔ purchase entries 1:1, (c) expired
pending liveness, and audits every flag.

**Consequences:** display surfaces (bot, Mini App, shared types) changed
wire shape (`BalanceOut.xp_per_sat`); the contract cannot drift again
because there is nothing left to drift - one setting, one computation site.
A receipt can never contradict the ledger because it is the ledger viewed,
not a copy.

## D13 - `task_events` as the 17th table; DB-checked approval and cancel (2026-10-15, phase 6)

**Context:** the plan's 16-table model predates the "task event stream and
progress updates" deliverable. The event stream could be squeezed into
`task_steps` or `audit_events`, or its own table.

**Decision:** add `task_events` (append-only, `(task_id, seq)` unique) as a
documented deviation: steps are state (current step status), events are
history (ordered, replayable, includes approvals/evaluation/outcomes) -
different consumers, different retention. Approval decisions and
cancellation are enforced DB-side: the runner re-reads committed state
(`approvals.status` for the exact action digest; `tasks.status` between
steps), so worker restarts and cross-process cancels are safe without
in-memory coordination.

**Consequences:** 17 tables now (migration `e5f6a7b8c9d0`); `audit_events`
stays minimal (digest-level tool facts), `task_events` carries the replay
stream with shape-level payloads (no raw tool output), keeping the stream
inspectable without leaking untrusted content into every consumer.

## D14 - Research tools: canned-search honesty, SSRF-walled fetch, provenance in the DB, quality gates in backend code (2026-10-15, phase 7)

**Context:** phase 7 asks for a web search adapter, permitted page
retrieval, a source citation/provenance model, cross-source comparison,
PDF/CSV/XLSX generation, private artifact storage, report quality checks,
and a repeatable evaluation set. Two hard constraints shaped everything:
(1) no search API key exists in this environment, and fabricating "search
results" would violate the plan's own research_quality rules; (2) retrieved
web content is untrusted and must not be able to reach private networks
(SSRF) or override policy (prompt injection).

**Decision:** a dedicated `research-adapter` package owns the network
boundary. Search is canned-only over the committed evaluation corpus and
labels itself as such on every response - an honest offline equivalent, not
a fake live web. Fetch has two transports: the same canned corpus, and a
real httpx provider behind `FetchPolicy` (http/https only, ports 80/443,
no userinfo, localhost/reserved hostnames denied, every resolved IP must be
globally routable - DNS rebinding fails closed, redirects re-pass the full
wall per hop, size + content-type caps). Provenance persists in an 18th
table, `research_sources`, keyed `(task, url)`: search listings start
`listed`, fetches upgrade to `ok`, and unavailable/denied/errored fetches
are KEPT as first-class records and disclosed - never silently dropped.
Facts are typed observed|estimate|assumption; price figures from listing
snapshots are typed `estimate` with a staleness note, so no listing price
can masquerade as a live quote. The report builder in the API assembles a
`ReportSpec` from durable rows; `xp_core.services.documents` enforces the
quality gates (every claim cited, every citation resolvable, duplicate-free
sources) and REFUSES to render violations, then validates generated files
by magic bytes/structure before private storage. The tool handlers return
shape only (ids, counts, fact keys) to the model - page content never
enters agent context raw.

**Consequences:** 18 tables (migration `a9b0c1d2e3f4`); `docs.generate_pdf`
in the product registry is real (the phase-6 stub plan cost math is
preserved, so the golden-path settlement is unchanged); the evaluation set
(`tests/data/research_eval_set.json` + `make research-eval`) makes the
quality bars a repeatable regression harness with 5 cases covering
citations, conflicts, unavailable disclosure, estimate typing, and the
honest-empty report. Live search awaits a search API key (tracked open
item); live fetch works wherever the sandbox has egress.

## D15 - Commerce intelligence: structural-only scoring, canned ad-library honesty, typed landed-cost template (2026-10-15, phase 8)

**Context:** phase 8 asks for product discovery, supported ad-library
integrations, trend scoring with transparent signals, supplier/listing
comparison, vehicle auction research, a landed-cost estimate template, and
source freshness/confidence indicators - under acceptance bars that forbid
inventing demand, ad-performance, or availability claims, and require
visible, configurable scoring factors.

**Decision:** a dedicated `services/commerce-adapter` package over the same
provenance records phase 7 persists (no new tables - verdicts live in
`task_events`, artifacts in `artifacts`). Scoring exposes EXACTLY five
structural factors (`distinct_sources`, `supplier_count`, `price_spread`,
`freshness`, `attribute_completeness`) with operator-configured weights
(`XP_COMMERCE_SCORING_FACTORS`); the weight configuration is echoed verbatim
in every verdict, any config defect falls back to documented defaults WITH a
disclosure, and factors with insufficient data are excluded with reasons
instead of silently zeroed. There is deliberately NO demand, ad-performance,
or availability factor - the platform cannot measure those from snapshot
pages. The ad-library integration is canned-only and says so on every
result; page-printed performance metrics stay in provenance but never enter
a summary or a score. The landed-cost template types every line
(asking price = estimate, official published rate = observed, user input =
assumption), states that no verified transaction cost exists in the
pipeline, and - when the model binds a source - takes the line VALUE from
the persisted fact, so citing [S2] with a different number is impossible.
Source freshness (fresh/recent/stale/outdated) and confidence (status +
retrieval mode + corroboration, capped at 0.9) ride along on every source
everywhere it is shown.

**Consequences:** the product registry gains six commerce tools under the
existing `research:read` scope (one scope wall, one budget gate, one audit
path); commerce fixture pages join the SAME canned providers, so search and
fetch reach them through the phase-7 permission wall unchanged; the
committed commerce evaluation set (`tests/data/commerce_eval_set.json` +
`make commerce-eval`, 7 cases) is the repeatable regression harness. A live
ad-library integration would require a permitted API partnership and is
tracked as an open item, honestly out of reach for now.

---

## D16 - Email + automation: preview-before-send, digest-bound expiring approvals, encrypted credential vault, budget-laddered scheduler (2026-10-15, phase 9)

**Context:** phase 9 asks for an external service connection framework, scoped
credential storage, email draft/preview, explicit send approval, scheduled
jobs, condition-based notifications, pause/resume/cancel/failure handling,
and run history - under five acceptance bars: valid authorization + approved
scope for every external action; approval bound to the exact action content
AND expiring; user-revocable connections; recurring jobs enforcing per-run
and total XP limits; and failed jobs never silently repeating consequential
actions.

**Decision:**
1. **Connections + vault.** One `ConnectedService` row per link; exactly one
   `ServiceCredential` row holding a Fernet ciphertext (key = sha256 of the
   operator master key, which itself is never stored). The plaintext has ONE
   decryption path (`vault.load_credential`) and never appears in logs,
   events, audit metadata, or API responses. Revocation hard-deletes the
   credential row - a revoked connection cannot authenticate even if other
   layers were bypassed. Dev mode may use a documented fallback key that is
   DISCLOSED on every surface; non-dev environments refuse to link without
   an operator key (`XP_CONNECTIONS_CREDENTIAL_KEY`).
2. **Email flow.** `email.draft` persists a draft with a content digest;
   `email.send` executes only post-approval, only for an UNSNT draft whose
   content matches the approved digest, and only against a linked
   connection with the `email:send` scope. Providers implement an honest
   taxonomy: `sent` / `refused` (definite, safe to report) / `unknown`
   (transport failed mid-session - the server may have accepted the
   message; the system records `unknown_outcome`, discloses it loudly, and
   NEVER auto-retries - mirroring the phase-3 wallet broadcast taxonomy).
   Default provider is canned with a no-network disclosure on every receipt;
   the real SMTP path (stdlib smtplib, off-loop) was proven against a local
   asyncio loopback server in tests.
3. **Approval expiry.** Approvals now carry `expires_at` (TTL,
   `XP_APPROVAL_TTL_MINUTES`, default 60). Reuse on resume only within TTL;
   expired-pending cannot be approved (the decision endpoint refuses with
   409 and marks it expired); approved-but-stale approvals are expired by
   the runner and a fresh decision is requested. Content binding was
   already digest-exact (D13); the time window completes the acceptance.
4. **Scheduler.** A deterministic schedule grammar (`every <n><s|m|h|d>`
   >= 60s, `daily HH:MM` UTC, `hourly`, `daily`) - full cron is a documented
   non-goal for this phase. Each run's task budget is
   `min(budget_per_run_xp, remaining_total)`; the ledger's cap refusal makes
   the per-run limit hold end-to-end, and an affordability pre-check records
   the skip cleanly without touching the ledger. Total budget exhausted ->
   run skipped AND job auto-paused with a notification. Consecutive failures
   (operator-configured ladder, default 3) auto-pause + notify. Every
   attempt - success, failure, skip, block - is an `AutomationRun` row.
5. **Consequential-action discipline.** A run whose spawned task awaits
   approval blocks (`blocked_on_approval`); subsequent sweeps WAIT - no new
   task, no new approval spam, no hidden resend. A denied approval fails the
   task explicitly with full reservation release. A worker crash mid-run is
   recovered by a staleness window (run marked failed, failure ladder
   applies); fresher runs are waited on, never run concurrently.
6. **Scope stacking.** `email:send` and `automation:write` join
   USER_TASK_SCOPES (they were structurally unreachable stubs before), and
   their tools still carry `requires_approval=True` - the scope wall and
   the approval gate stack; untrusted content cannot bypass either.

**Rejected alternatives:** storing credentials as environment variables per
user (unscalable, unauditable); auto-retrying email on unknown outcomes
(could double-send - the exact acceptance violation); full cron parsing
(dep-heavy, easy to get DST/timezone wrong silently); silently ignoring
unknown condition keys (typo -> job that never notifies looks healthy);
resuming a denied-approval task (would re-request approval forever).

**Consequences:** notifications are persisted + API-readable with Telegram
relay as an open item (pretending to push without a bot token would
fabricate delivery). Live SMTP delivery needs a real server + an operator
master key; everything else is fully testable offline. The automation sweep
runs in the worker cron (arq) and inline in dev; one broken job never kills
a sweep (per-job error isolation with logged outcomes).

## D17 - Operations readiness: alerts as a first-class table, code-pinned rate classes, drills as committed code (2026-10-16, phase 10)

**Context:** phase 10 demands abuse controls, payment reconciliation
alerts, backup/restore drills, retention policy, and observability. The
economy already had a read-only reconciliation sweep that audited
discrepancies into the audit log.

**Decision:**
- *Reconciliation alerts* become the 23rd table
  (`reconciliation_alerts`) with an operator lifecycle (open →
  acknowledged → resolved). Dedupe is application-level (one live row per
  kind+subject; repeats bump `last_seen_at`), because resolved history
  must survive for forensics. Critical (money-integrity) kinds are never
  auto-resolved - a mismatch that stops being observable is evidence, not
  resolution. Only housekeeping warnings (expired-pending) auto-resolve.
- *Rate limiting* is an in-process token bucket over five code-pinned
  route classes (auth/money/agent/read/write), keyed by client IP + bearer
  fingerprint without a DB hit; monitoring surfaces are structurally
  exempt; `XP_RATE_LIMIT_ENABLED` is the kill switch. The Redis backend
  (same interface) is the documented multi-worker upgrade path, not a
  phase-10 dependency.
- *Retention* is one deterministic sweep with per-window settings and a
  structural PRESERVED_SURFACES list - the money trail and evidence trails
  (ledger, intents, task_events, audit_events) cannot be swept even by
  misconfiguration.
- *Drills and audits are committed code* (`scripts/backup_drill.py`,
  `scripts/dependency_audit.py`, make targets), not wiki instructions: the
  drill re-runs reconciliation on the restored copy, and the audit gate
  fails the build on unpinnable dependencies/images while honestly
  disclosing that live CVE scanners are not bundled.
- *Ops surfaces* (`/ops/*`) are DEV_MODE-gated system seams, consistent
  with `/xp/reconcile`; production requires real operator access control
  first (KL-11).

**Alternatives rejected:** auto-resolving critical alerts (hides
intermittent corruption); per-endpoint rate-limit decorators (scattered,
easy to forget on new endpoints); retention by hard-coded days (operators
lose privacy-tuning ability); a wiki runbook for backup/restore (drifts
from code, unverifiable).

**Consequences:** operators can now *detect, queue, and acknowledge*
payment discrepancies rather than grep logs; abuse has a ceiling per
surface; restoring a backup is a verified procedure, not a hope. The full
honest gap list (multi-process rate limits, Postgres/SCB restore
rehearsal, operator identity for /ops) lives in
docs/known-limitations.md KL-04/KL-05/KL-09/KL-11.

## D18 - Notification relay: one push decision per notification, honest sent/refused/unknown/skipped taxonomy (2026-10-16, KL-06)

**Context:** phase 9 left the Telegram notification relay open (D16) -
notifications were persisted and API-readable but never pushed, and
pretending to push without a bot token would fabricate delivery. Closing
the loop means the worker now sends to Telegram, which re-introduces the
exact uncertainty the email adapter (phase 9) already solved for SMTP:
after a send attempt, did the message actually arrive?

**Decision:**
- *Exactly one relay decision per notification.* A worker cron sweep
  (`xp_core.services.relay`) terminates every never-relayed notification
  in one of four states recorded in `relay_status` + `relay_detail` +
  `relayed_at`: `sent`, `refused`, `unknown`, or `skipped`. Nothing is
  ever attempted twice; a second sweep over the same rows is a no-op.
- *Refusals are terminal, not retried.* Telegram refuses definitively with
  a 4xx (blocked bot, chat not found, bad token). Retrying a refusal only
  spams the chat and burns rate limits - the refusal detail is recorded
  instead.
- *Unknown outcomes are never silently retried.* Timeout, transport error,
  or 5xx means the send MIGHT have completed; the row records the
  never-auto-retry disclosure, mirroring the email taxonomy and the
  phase-3 wallet broadcast rule.
- *Skips are decisions too.* Read in-app before the push (pushing would be
  noise), no linked Telegram account, or past the 24h lookback window
  (backlog flood guard) each record `skipped` with the reason.
- *Twin providers, one code path.* `CannedTelegramRelayProvider`
  (deterministic, no network, receipt states nothing was transmitted) and
  `BotApiTelegramRelayProvider` (real sendMessage, transport-injectable for
  offline tests) share one interface selected by
  `XP_TELEGRAM_RELAY_MODE=canned|bot_api`; `bot_api` refuses to construct
  without a token - no silent downgrade of a requested real send.
- *The API discloses the decision.* `NotificationOut.relay_status` is
  user-visible; the Mini App can show exactly what happened to each push.

**Alternatives rejected:** retry queues with backoff (turns unknown into
possible double-send); pushing read notifications (spam after the user
already saw it); unbounded backlog push when a token first arrives (flood);
embedding the provider in xp_core (inverts the dependency direction the
email adapter established - worker wires provider into the core service).

**Consequences:** automation is now felt, not just trusted - condition
notifications arrive in the user's chat with a per-notification audit
trail. The sweep is deterministic and fully testable offline; live-mode
evidence (real token + chat) remains an operator step, tracked in
docs/known-limitations.md KL-06 as closed-with-residual.

## D19 - Self-serve closure: refuse-while-in-flight, reconcile-then-anonymize, never a fabricated forfeit (2026-10-16, KL-10)

**Context:** the privacy policy documented account closure as a manual,
human-coordinated process because the money trail is immutable: ledger
entries, payment intents, task events, and audit events cannot be deleted,
so "delete my account" can never mean a clean wipe. Self-serving it without
guardrails would either orphan the evidence trail or invite users to close
with money in motion.

**Decision:**
- *Export is a superset download with disclosed holes.* One JSON document
  covers every owned surface; session token hashes and Fernet credential
  ciphertexts are never exported and the document says so itself.
- *Closure refuses with precise reasons while anything is in flight:*
  running tasks, pending approvals, open payment intents, nonzero XP
  balance. A nonzero balance blocks closure outright - there is NO
  fabricated "forfeit" ledger entry, because writing a fake economic event
  to keep the invariant would be the exact fabrication the ledger exists
  to prevent. Balance reaches zero through real events or operator help.
- *Reconciliation gate before erasure:* `reconcile_all` must report clean
  (balance == sum of ledger entries) or closure refuses - the documented
  "reconcile the immutable ledger before anonymizing identity rows" rule,
  now enforced in code.
- *Erasure levels are explicit:* user content and auth surfaces are hard
  deleted (including artifact files on disk and wallet server state);
  identity is unlinked (telegram rows deleted, display name dropped,
  status=closed); content-bearing fields of structural rows are scrubbed
  in place (task objectives, job templates) so append-only evidence stays
  resolvable; the money/evidence trail is retained untouched.
- *Typed confirmation on the wire* (`confirm: "CLOSE"` as a Literal) and a
  two-step confirm in the Mini App; closure erases sessions, so the bearer
  token cannot outlive the account.

**Alternatives rejected:** a forfeit/adjustment ledger entry to zero the
balance automatically (fabricates an economic event); deleting the user row
(breaks every FK into the retained evidence trail); deleting tasks and jobs
rows wholesale (orphans task_events/automation evidence and ledger
references); keeping PRESERVED_SURFACES semantics for closure (that
instrument constrains the automatic sweep, not an explicit authenticated
user action - the two are now documented as distinct).

**Consequences:** the Btrust privacy story is complete - users can take
their data and leave, and leaving provably cannot corrupt the ledger.
Residual: closure with a balance needs operator contact (honest, disclosed
in the refusal reasons).

## D20 - Rate-limit backend swap + validation-joined keys: shared buckets across workers, rotation-proof subjects (2026-10-16, KL-09)

Phase 10 shipped honest, code-pinned token buckets, but with two disclosed
residuals: buckets lived per API process (a multi-worker deployment
under-limits by the worker count) and the subject was keyed on the PRESENTED
bearer fingerprint, so a client rotating fake or fresh tokens could refresh
its bucket at zero cost. Both were tracked as KL-09 and named as the abuse
surface to close before any multi-worker production claim.

**Context:**
- The limiter deliberately avoids a database hit in the hot path; keying on
  the authenticated user naively would mean validating the bearer inside the
  middleware, duplicating the auth dependency's work per request.
- Multi-worker enforcement needs state that outlives one process; the
  in-memory buckets cannot provide it by construction.
- An abuse limiter must never become an availability problem: deciding what
  happens when the shared store is down is part of the design, not an
  afterthought.

**Decision:**
- *One interface, two backends, a refusing factory.* `RateLimiter` (memory,
  default) and `RedisRateLimiter` (shared) expose the same `check`
  contract; `build_rate_limiter(settings)` selects by
  `XP_RATE_LIMIT_BACKEND`. `backend=redis` without `redis_url` refuses to
  construct so a requested shared backend is never silently downgraded to
  per-process memory.
- *The Redis bucket is one atomic Lua script* (pinned as TOKEN_BUCKET_LUA):
  read tokens+timestamp, refill by elapsed time (negative drift clamped so
  skewed clocks can only slow a refill, never move tokens backward), decide,
  write back, refresh the idle TTL. One round trip, no read-modify-write
  races between workers. The committed FakeRedis test double mirrors this
  script line for line and asserts it executes the pinned script.
- *Validation-joined subjects close the rotation hole without a second DB
  hit.* The auth dependency already validates every bearer; it now feeds
  each successful validation into a process-local, TTL- and size-bounded
  `IdentityCache` (bearer fingerprint -> `user:<id>`). Subject derivation
  prefers the joined user, so every valid token of one user drains ONE
  bucket regardless of rotation. A bearer never seen valid (forged, cold)
  falls back to the ip:fingerprint subject - a one-request seam, disclosed,
  never a permanent bypass.
- *Degraded means fail OPEN with disclosure, never a fabricated decision.*
  On any Redis error the limiter allows the request, marks the result
  degraded, counts it, and rate-limits the warning log; the middleware
  reports `X-RateLimit-Remaining: unknown` instead of an invented count and
  /ops/observability carries the backend name plus the degraded counter.
  Fail-open was chosen over fail-closed because a limiter outage must not
  take money and agent surfaces down with it; the honest counter is the
  operator's signal to act.

**Alternatives rejected:** fail-closed on backend error (the limiter would
DoS its own API); fixed-window INCR counters (changes semantics from the
documented token bucket); validating bearers inside the middleware (a second
DB hit per request and a duplicated auth path); a shared bucket keyed only
on IP (breaks concurrent legitimate sessions behind one NAT).

**Consequences:** the multi-worker abuse claim no longer depends on an
undeployed upgrade path - the backend is in the tree, configurable, and
tested offline. Residuals: live multi-worker evidence awaits an operator
host with a real Redis; a Redis outage degrades to fail-open (disclosed,
counted, never silent); the identity join warms on the first validated
request of each token.

## D21 - Operator identity for /ops: a configured credential, dark-without-it, audited at every door (2026-10-16, KL-11)

Phase 10 gated `/ops/*` on DEV_MODE only - the honest phase-10 scope, but it
meant production operator access depended entirely on the operator putting
something (VPN, mTLS, an admin authenticator) in front of the API, and
nothing in the code helped or verified that. F-03 named it a must-close
before any non-dev deployment; KL-11 tracked it.

**Context:**
- The ops surfaces expose money-integrity state (reconciliation alert queue,
  observability counts). Serving them unauthenticated in production would
  leak operational posture; refusing them outright in production left
  operators with no in-product path at all.
- There is no operator user model (operators are not accounts in the users
  table, and the user auth wall must not grow an admin role lightly - a
  compromised admin user row would sit inside the same credential-stuffing
  blast radius as every other user).

**Decision:**
- *A configured credential, required everywhere it exists.* Setting
  `XP_OPS_OPERATOR_TOKEN` makes the credential REQUIRED for every ops
  request in every environment, dev included - an operator who sets a token
  wants it enforced, so dev never becomes the quiet bypass. Comparison is
  constant-time (`hmac.compare_digest`); the credential is accepted via
  `X-Operator-Token` or a standard Authorization bearer, never logged, never
  echoed.
- *Without a credential the surfaces stay DARK, not open.* No credential +
  non-dev refuses 503 with an honest detail; a missing operator setup can
  never silently degrade into public access. No credential + DEV_MODE keeps
  the unchanged local convenience (that is what DEV_MODE is for).
- *Every door is audited.* Grant and denial each write an audit_events row
  (`ops.access_granted` / `ops.access_denied`) carrying method, path,
  header source, denial reason, and a fingerprint of the presented
  credential for retry correlation - never the credential itself. Denials
  are attempted-access evidence, not noise to suppress.
- *The credential authorizes ops, nothing more.* It is not a user session:
  user endpoints reject it, and the fabrication walls (`/xp/dev/grant`,
  manual reconcile) stay dev-only with an operator credential presented.
  Operators run the integrity queue; they cannot mint balances.
- *Router-level dependency* (`require_operator` on the /ops router) so a
  future ops endpoint cannot forget the gate - the gate is the router's,
  not each handler's discipline.

**Alternatives rejected:** reusing user sessions with an admin flag (puts
the most powerful capability inside the largest credential-stuffing surface);
fail-open to DEV_MODE behavior when no credential is set (that is exactly
the silent-public-access failure F-03 warned about); per-request JWT ops
tokens (no issuer infrastructure exists to rotate/verify them - a static
high-entropy credential with audit + rotation guidance is the honest
provable step).

**Consequences:** /ops is deployable behind a configured secret today, and
unusable-by-construction without one. Residual: the credential is a shared
static secret (no per-operator identities, no VPN/mTLS integration) - the
next hardening step for larger teams; manual reconcile and dev grants stay
dev-only by design.

## D22 - The wallet moves onto the user's device; the server wallet is retired (2026-10-20)

**Context:** the server-side BDK wallet generated the phrase on the server and
needed it back to unlock and sign. Whatever the TTL, that is server-assisted
custody, and Bitcoin reviewers would rightly reject the "self-custody" claim.

**Decision:** generate, store (password-encrypted) and sign entirely in the
Mini App with `@scure/bip39`, `@scure/bip32` and `@scure/btc-signer`; read
the chain and broadcast through Esplora (mempool.space). Delete the server
wallet API, service and adapter. Keep the empty tables for migration safety.

**Consequences:** the server holds nothing that can move user funds. Device
loss is covered by the 12 words and the optional encrypted Telegram backup
(D25). Privacy trade-off: the Esplora host sees queried addresses (KL-17).

## D23 - XP is paid in real bitcoin to the operator's watch-only wallet (2026-10-20)

**Context:** XP purchases used a simulated Lightning settle button.
BTCPay Server was considered, but needs its own full node and its testnet4
support was unclear, while the app wallet uses testnet4.

**Decision:** `XP_PAYMENT_MODE=onchain`. Each purchase gets a fresh BIP84
address derived from `XP_ONCHAIN_XPUB` (public key only; the operator's phrase
stays offline, made with `deploy/make_payment_wallet.py`). The API and a
one-minute worker sweep check the address via Esplora; when it has received
at least the amount with `XP_ONCHAIN_MIN_CONF` confirmations, a CAS moves the
intent to settled and the ledger credits `purchase:{intent_id}` exactly once.
Late payments to an expired request are still credited for 7 days.

**Consequences:** real money, no custody of user funds, no node to run.
On mainnet, on-chain fees are large relative to the smallest pack (KL-16);
Lightning remains the path for small payments.

## D24 - Buying bitcoin goes through Onramper to the user's own address (2026-10-20)

XP never sells bitcoin or touches fiat. The Buy screen asks the API to sign
an Onramper widget URL (V2: Ed25519, canonical 8-line string) with the
user's own receive address pre-filled; Onramper's licensed partners take the
naira payment and deliver to that address. Mainnet addresses only; off until
`XP_ONRAMPER_API_KEY` and `XP_ONRAMPER_SIGNING_KEY` are set, with a "buy on a
Nigerian exchange and withdraw to your address" guide as the fallback.

## D25 - Encrypted wallet backup in the user's Telegram Cloud Storage (2026-10-20)

The phrase is stored there in the same password-encrypted box as on the
device; a random backup key (itself password-encrypted) encrypts the address
book so contacts can sync on every change without asking for the password.
Neither Telegram nor XP can read it. Restore needs only the password; the
user can turn it off (deletes it) or delete it when removing the wallet.

## D26 - Dev mode fails closed (2026-10-19)

`XP_DEV_MODE` defaults to false and is refused outright when `XP_ENV` is
`staging` or `prod`, because dev mode disables authentication. The demo's
canned Lightning button has its own flag (`XP_DEMO_LIGHTNING_SETTLE`) so
demos never need dev mode on a public server.

## D27 - @usernames and shareable payment requests without giving up self-custody (2026-10-21)

**Context:** users want to pay "@ada" instead of a long address, and to share
"pay me" links on WhatsApp. The obvious design (give the server each user's
xpub) would let XP see every balance and payment.

**Decision:** the phone uploads a pool of its own receive addresses (index
1000+ on the receive chain), each signed with a wallet identity key on a
private chain (m/84'/coin'/0'/7/0; it can vouch for addresses but never spend).
The server verifies every signature, hands out one unused address per payment,
and never sees the xpub. Payers' phones re-verify the signature and pin the
identity key on first payment (warning if it changes), so a compromised server
can't substitute its own address. Payment requests reuse the pool: a public
`/pay/<id>` page (works outside Telegram) shows the request and a verified
address; the API and a worker sweep mark it paid and notify the owner through
the existing Telegram relay. Names: 3-20 of `[a-z0-9_]`, reserved words
blocked, released names held 30 days.

**Consequences:** the server learns which payments went to which username
(disclosed), but not balances or other activity. The identity key is stored
unencrypted on the device so pools top up silently; it cannot move funds.

## D28 - Full wallet life cycle: recovery, stuck payments, alerts, leaving (2026-10-22)

**Context:** a wallet people trust with real money has to handle the bad days:
a new phone, a forgotten password, a payment stuck for days, an incoming
payment nobody noticed, and the day they want to leave.

**Decisions:**
- **Restore finds @username coins.** The receive pool (index 1000+) is always
  gap-scanned, and the server's "issued up to" index is fetched even before
  the wallet knows its username. A phone restored on a different Telegram
  account still finds payments made to @username.
- **Speed up / cancel (BIP125 RBF).** Every payment already signals
  replaceability. A pending payment can be re-sent with a higher fee (same
  recipients, fee from change or a spare confirmed coin) or cancelled (all
  inputs back to a fresh change address). The new fee beats the old one by
  at least 1 sat/vB of the new size, and the rate always goes up. Payments
  whose change another pending payment already spends are not offered
  (replacing them would invalidate the child).
- **Payment alerts are opt-in and watch-only.** The phone shares only the
  receive addresses it shows (never the xpub); the server also watches the
  @username addresses it handed out, but skips payment-request addresses,
  which already have their own message. First check records existing
  history without messaging; afterwards each payment gets at most one
  "receiving" and one "confirmed" message. Turning alerts off deletes the
  watched addresses; account closure erases them.
- **Safety prompts.** Paying an address not in contacts/@username, a payment
  of half the balance or more, or a fee above 20% of the amount needs an
  explicit "I've checked" tick. Optional app lock (password on open and after
  5 minutes away), hide-balance toggle, plain "forgot password" path.
- **Offline.** The last known balance and history are cached on the device
  and shown with "last updated"; sending waits for fresh data.
- **Leaving / inheritance.** Export of the public key and BIP84 descriptors
  (watch in Sparrow etc.), "move everything" (send max), CSV history, and a
  plain-language recovery and family guide (`/recovery`).
- **Mainnet beta limit.** Above `NUXT_PUBLIC_WALLET_BETA_LIMIT_SATS`
  (default 1,000,000) the wallet advises keeping only spending money here
  until an independent review (KL-15). It never blocks the user's own funds.

**Consequences:** with alerts on, the server learns the watched addresses and
their incoming payments (disclosed on the opt-in screen). Payment notes are
stored on the device and in the encrypted Telegram backup only.

## D29 - Lightning on the phone with the Breez SDK (Spark) (2026-10-22)

**Context:** on-chain fees make small everyday payments (a ₦500 top-up,
lunch) uneconomic. Running our own Lightning node would mean holding
liquidity and operating channels for every user, and a custodial Lightning
account would break the "only you hold the keys" promise.

**Decision:** add a Lightning wallet that runs on the user's phone using the
Breez SDK on Spark (`@breeztech/breez-sdk-spark`, WebAssembly):
- **Same 12 words.** The Lightning wallet is opened from the same recovery
  phrase (decrypted with the wallet password once per session, never stored
  in plain form). One backup covers savings and Lightning, and the funds can
  also be restored in other Breez SDK (Spark) wallets.
- **Self-custodial, with a disclosed trust assumption.** Keys stay on the
  phone. Spark transfers are co-signed by a small set of independent
  operators (Lightspark, Breez, Flashnet); they can't move funds alone, and
  the user can always exit to the Bitcoin blockchain unilaterally.
- **What users can do:** receive with an invoice (any Lightning wallet can
  pay it) or a reusable Spark address, send to invoices, Lightning addresses,
  LNURL-pay and Spark addresses (unified QR codes prefer Lightning), see
  history, get `username@breez.tips` as a Lightning address on mainnet, and
  move money between savings and Lightning in one tap on mainnet.
- **Networks.** With the testnet wallet, Lightning runs on Spark's regtest
  network (free coins from the Lightspark faucet, no API key). Because
  testnet4 and regtest are different chains, moving between savings and
  Lightning is mainnet-only, and the app says so. Mainnet needs a free Breez
  API key (a client key, `BREEZ_API_KEY`).
- **Performance.** The SDK (12 MB WebAssembly, 3.9 MB with brotli) is loaded
  only when the user opens Lightning and is cached by the browser after.
- **Locking.** The Lightning session is closed when the app locks or the
  wallet is removed.

**Consequences:** TK purchases are still paid on-chain to the operator's own
wallet; paying TK from the Lightning balance needs the server to accept
Lightning (next step). Spark's operator model is a weaker guarantee than a
plain on-chain wallet and is disclosed as such.

## D30 - One unlock for both wallets; polite chain lookups (2026-10-22)

**One password, one session.** "Unlock Satish" decrypts the recovery phrase
once and keeps it in memory for the session; it opens Lightning and lets
Bitcoin payments, speed-ups and cancels go through without asking again.
Showing the 12 words, changing the password and exporting still ask. "Lock
now", the app lock (on open and after 5 minutes away) and removing the wallet
drop the phrase from memory and close Lightning. The home screen has a
Bitcoin / Lightning switch showing both balances.

**Chain lookups.** mempool.space rate-limits bursts, and inside Telegram a
rate-limited reply surfaces only as "Failed to fetch", which left the Bitcoin
side stuck on "Updating…". The Esplora client now paces request starts
(~8/s), runs at most 3 at once, slows down automatically on push-back and
speeds up again on success, and retries network errors, 429 and 5xx with
back-off (broadcasts are never blindly retried). Syncs are single-flight,
the change chain look-ahead is 10, and the @username pool look-ahead is 20
only on a device's first sync (5 after). "Review" waits for an update in
progress instead of failing.

## D31 - Pay @username on Lightning (2026-10-23)

**Decision:** when a user opens Lightning, their phone publishes their Spark
address under their @username, signed by the same wallet identity key that
vouches for their on-chain pool addresses (message
`sha256("xp-handle-ln-v1|<network>|<ln network>|<address>")`). The server
checks the signature and that the key owns the username before storing it.
Paying "@ada" on Lightning fetches her signed address; the payer's phone
re-verifies the signature, checks the Lightning network matches, and checks
the identity key against the one pinned the first time they paid her (on
Bitcoin or Lightning), warning if it changed. The payment is a Spark transfer:
instant and free. Saved Satish contacts are suggested as you type.

**Consequences:** a compromised server can't redirect @username Lightning
payments (it can't forge the signature). If the recipient has never opened
Lightning, the payer is told to pay on Bitcoin or ask them to open it once.

## D32 - Two-part app, instant sync, private keys (2026-10-23)

**Navigation.** Two main tabs: **Wallet** and **Satish AI**, each with its
own sub-tabs. Wallet: Home (Bitcoin / Lightning switch), History (Bitcoin |
Lightning), Activity (Bitcoin: payments waiting to confirm, payment requests,
alerts; Lightning: in-progress/failed payments, deposits, @username status),
Address book, Settings. Satish AI: Assistant, Tasks, Automations, Buy TK, TK
history, Connect. Wallet sections are `/?s=<section>` so the existing wallet
flows (send, receive, speed up...) keep working from any section.

**Instant sync.** The cached balance shows immediately; a quick sync then
re-checks only addresses in use plus a few fresh ones (receive x2, change x1,
@username pool up to what was handed out), downloads history/coins only for
addresses whose numbers changed (per-address cache in the device snapshot),
and fetches the username in parallel. A full gap scan runs on first sync /
restore, every 30 minutes, when a fresh address turns out used, or on
"Check all". Requests use a token bucket (burst 6, then ~6.6/s, slowing on
push-back). Measured against a server limited to 8 requests/s: reopening a
funded wallet is fully synced in 0.25-0.4 s with no rate-limit hits.

**Private keys.** Settings -> Private keys: the account private key (xprv /
tprv, BIP84) and descriptor, plus per-address keys for addresses holding
coins, behind the password and an explicit "I understand" tick. "Sweep a
private key" moves everything on a WIF key (native SegWit, nested SegWit or
legacy) into the wallet; the key is never stored.

## D33 - Product design pass (2026-10-23)

Audit of every screen at phone size, then fixes:
- **Frame:** removed the brand header and footer (Telegram already shows the
  app name); main sections moved to a bottom bar (Wallet, Satish AI) within
  thumb reach; sub-tabs sticky at the top; wallet sub-tabs hidden until a
  wallet exists. Chrome above content went from ~235 px to ~50 px.
- **Home:** balance leads with sats (naira and BTC secondary); Receive and
  Send are the two primary actions, Buy bitcoin and Request secondary; the
  big Refresh button became a quiet "Updated just now · tap to refresh"
  line. Lightning card matches (same balance style and action layout); its
  "How safe is it?" is a pop-over instead of a paragraph on every visit.
- **Send:** the fee picker shows time and typical cost (sats / naira)
  instead of sat/vB, as three equal options.
- **Settings:** grouped list (Security, Backup and alerts, Your wallet
  elsewhere, Account) with switches for on/off settings and the destructive
  action last; no more endless "…" when the alerts status can't be loaded.
- **Satish AI:** one name everywhere; sub-tabs Ask, Automations, Credits,
  Connect (Buy TK + TK history merged into Credits); tasks as a phone list
  instead of a 6-column table; budget shown in sats/naira; an everyday
  Nigerian example instead of a technical one; credit packs lead with TK and
  show price in sats and naira; removed the misleading "≈ sats equivalent".
- **Detail:** day-first dates without seconds ("22 Oct, 09:00"); sentence-
  case table headers; emoji removed from headings; visible keyboard focus;
  reduced-motion respected; clear offline message.

## D34 - Satish AI tasks that never finished (2026-10-24)

**Symptom:** every task, even "hello", stayed on "Working on it…" forever.

**Causes found:**
1. Pressing Run marks a task `running`, but `started_at` was only set when a
   worker actually began it. The safety watchdog only looked at `started_at`,
   so a task no worker ever picked up was invisible to it: stuck forever,
   TK held.
2. AI tasks shared the one arq worker (4 slots) with seven every-minute
   sweeps (payments, requests, alerts, relay, automations, watchdog). A slow
   sweep (e.g. alerts when mempool.space is slow) holds slots while new
   minute runs keep queueing, so AI tasks can wait behind them indefinitely.
3. "hello" couldn't even be created: objectives needed 8+ characters, and
   the browser's own warning isn't shown inside Telegram.
4. The AI client stacked the OpenAI SDK's own retries on top of ours.

**Fixes:** a dedicated `ai-worker` service on its own queue (`satish:ai`);
every-minute sweeps get a 55 s time limit; `tasks.queued_at` is recorded on
Run and the watchdog also stops tasks not started within 3 minutes (and old
stuck ones), returning their TK with a plain message; the app shows
"Waiting to start…" vs "Working on it…" and an "offline" banner from the AI
worker's heartbeat (`GET /tasks/ai-status`); 2-character objectives allowed;
SDK retries off (45 s timeout); failure messages say what went wrong (AI key
refused, out of credit, couldn't reach the AI service). Verified with real
Redis + both workers: "hello" goes queued -> running (0.5 s) -> done (2.6 s).

## D35 - Satish AI with a real model (2026-10-24)

The agent loop had only ever run against the built-in stub (KL-01). With
DeepSeek it broke in three ways: tool names such as `web.search` were sent as
function names (the API only allows letters, digits, `_` and `-`), the plan
request offered functions while asking for JSON (real models answer with a
function call or prose, which parsed into an empty plan), and nothing wrote
an answer from the results. Now: tools are described in the prompt and the
plan is requested with `response_format: json_object`; replies are parsed
robustly (code fences, loose tool names like `web_search`, unknown tools
dropped, plain prose treated as the answer); greetings and general-knowledge
questions are answered directly in one call; research tasks run their tools
and then a second call writes the answer from the (untrusted) results. The
full answer is stored with the task and shown in the app.

## D36 - Satish AI is isolated from the wallet (2026-10-24)

Satish AI has no wallet tools, no wallet wording in its prompt, and its code
may not import wallet modules (handles, on-chain, Lightning, wallet alerts).
`tests/test_ai_isolation.py` enforces all three. Paying someone by @username
is a wallet feature and never goes through the AI. The AI worker's Redis is
addressed as `satish-redis` because the api container also joins booklet's
network, where `redis` resolved to booklet's Redis and jobs never arrived.

## D37 - Real research, results delivered to Telegram (2026-10-24)

Research is live by default in production: Brave Search when
`XP_BRAVE_SEARCH_API_KEY` is set, otherwise keyless web search; pages are
fetched over HTTP behind the FetchPolicy wall and a bounded excerpt
(untrusted data) is shown to the model. The planner re-plans after each
search/fetch, so it reads real URLs from the results instead of guessed
placeholders, and never repeats an identical step. PDFs include the written
report as well as the source appendix.

A finished task is sent to the user's Telegram chat with the bot (answer as
messages, files as documents). Once Telegram accepts them, our copies of the
files are deleted and the task's answer, page facts and plan are scrubbed, so
history lives in Telegram. If delivery fails nothing is removed and the app
offers "Send to my Telegram chat". Users can delete a task or clear all
finished ones; the bare row stays because TK ledger entries reference it.

Automations accept every N minutes/hours/days, daily at several times,
weekly on chosen days, monthly on a day, each in the user's own time zone
(`daily 08:00,18:30 tz Africa/Lagos`).

## D38 - TK v2: automatic charging, welcome TK, buy any amount (2026-10-24)

- No budgets to type. A task holds up to `XP_AGENT_AUTO_BUDGET_XP` (1,000)
  of the balance, or the whole balance if lower, while it runs; only what
  it uses is charged and the rest returns at once. Tasks start immediately.
  Automations do the same per run.
- Every account gets 300 TK once (`welcome` ledger entry keyed per user;
  existing accounts receive it on their next sign-in).
- 1 sat = 5 TK. Users type how much TK they want (minimum 500 TK = 100
  sats; sats round up, so TK credited is always sats x 5).
- Users choose Lightning or Bitcoin. Both pay the operator directly:
  Bitcoin to a fresh address from `XP_ONCHAIN_XPUB` (watch-only); Lightning
  to a per-purchase invoice from the operator's Breez Spark wallet running in
  the API (`XP_TK_LIGHTNING_MNEMONIC`). The invoice is exact and unique, so a
  payment can only credit its own purchase; the API checks every 15 s and on
  each poll, and credits once (compare-and-set + `purchase:{intent}` key).
  `XP_TK_PAYEE_USERNAME` is shown as "Paying to @name". The pay screen has a
  QR, copy buttons, and "Pay with my Satish wallet" for both methods.
- Trade-off: the Lightning phrase on the server can spend that wallet. Keep a
  small float and sweep income out regularly.

## D39 - TK paid into the owner's own Satish wallet (2026-10-24)

`XP_TK_WALLET_MNEMONIC` takes the 12 words of the owner's Satish wallet and
sets up both methods: Bitcoin addresses come from the same BIP84 account
(m/84'/coin'/0'), Lightning invoices from the same Spark wallet. TK addresses
use receive index 5000+, apart from the app's own Receive addresses (0/0..)
and the @username pool (0/1000..), so the owner's personal payments can never
be mistaken for a purchase. Expired, never-paid addresses are reused after a
day, keeping the range compact; the Satish app scans 0/5000+ (one batch of
five for everyone else) so the owner sees the income. Same addresses on both
sides verified against the BIP84 test vector.

## D40 - Two modes: Telegram Mini App and browser extension (2026-10-27)

One Nuxt app, two builds. `SATISH_TARGET=extension` (apps/extension/build.mjs)
makes a Manifest V3 side-panel extension: hash routing, no Telegram SDK, no
inline scripts or import map (moved to files for the extension CSP),
`wasm-unsafe-eval` for the Lightning module. `usePlatform()` holds the
differences. Sign-in links the extension to the user's Telegram account: the
extension shows a code, the user sends `/link CODE` to the bot, the bot
confirms with a key derived from the bot token, and the extension (polling
with a secret only it holds) receives a 30-day session once. Same account,
TK and tasks; the wallet stays per device. Extension-only extras use context
menus, not content scripts: "Ask Satish AI about this page/selection" and
"Pay with Satish" for lightning:/bitcoin: links and selected invoices.
Verified by loading the built extension in Chromium.

## D41 - Money in your language and currency, chat AI, social features (2026-10-27)

- Amounts: `GET /price/rates` gives BTC in every currency (CoinGecko market
  rates first, open.er-api.com cross rates for the rest). `AmountInput` lets
  people type sats or any currency in send, receive and request; what is sent
  is always the sats shown at that moment.
- Languages: 12 (en, pcm, ha, yo, ig, fr, ar RTL, sw, pt, es, am, zu) via a
  small built-in translator; main screens translated, the rest falls back to
  English. Satish AI answers in the user's language (task.language, Telegram
  language_code in chat). Nigerian-language strings need native review.
- Satish AI chat in Telegram: private messages become tasks in a thread
  (`tg-<id>`); the last turns (24 h) give follow-up context; memories
  (auto-extracted or "remember ...") are visible and deletable; /new, /forget.
  PDFs and text files sent to the bot are read in memory and answered.
  New tools: `data.rates` (live rates) and `math.calculate` (exact maths).
- Price alerts (fire once via the relay) and savings goals (progress computed
  on the phone; the server never sees balances).
- Group pay: `/pay ₦2000 @musa` and `/split ₦10000 @a @b dinner` post cards
  with a Mini App link (start param `gp_<id>`); payers pay from their own
  wallet and the card ticks them off.
- Social recovery: the phrase's entropy split 2-of-3 with Shamir over
  GF(256), with a checksum so wrong pieces are caught. Shares are sent to
  trusted people via Telegram's share sheet; restore accepts any 2.
- Daily spending limit (per device): over it, Send waits 30 seconds.

## D42 - Satish for developers: API keys, payment requests, webhooks (2026-10-29)

Wallet > Settings > Developers. Keys (`sk_test_` / `sk_live_`, sha256 stored,
shown once) can only create, read and cancel payment requests for their
owner: no balances, no spending. `POST /dev/payment-requests` takes sats or
an amount in any currency, `metadata` and `redirect_url`, and returns
`pay_url`, `telegram_url` and a `bitcoin_uri`. Money goes to a fresh address
from the owner's own @username pool, so Satish never holds it. When the
chain sweep marks a request paid, a `request.paid` webhook is queued for
each endpoint; the worker POSTs it (every 30 s) with
`Satish-Signature: t=..,v1=HMAC-SHA256(secret, "t.body")`, retrying with
backoff (30 s .. 6 h) until a 2xx. Webhook URLs must be https on public
addresses (resolved and checked before every send).

Lightning (D43, 2026-10-29): the developer's Lightning wallet is on their
phone, so the server can't see payments to it. For API requests Satish's own
Lightning wallet (the operator wallet) issues the invoice, marks the request
paid the moment it settles (webhook `paid_via: lightning`), then forwards the
sats to the owner's published Spark address (idempotent per request, retried
up to 6 times, then `forward_status: failed` for the operator). Satish holds
the money only for those seconds: the owner chose this over a slower
non-custodial design so webhooks work. `methods: ["onchain"]` opts out.
