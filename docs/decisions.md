# Decision Log

Living record of architecture decisions and their status. Format follows the
plan's guidance: document the decision, the trigger for revisit, and the
honest current state.

## D1 — Python workspace packaging: `packages/py-core`

**Decision:** introduce a shared internal Python package (`xp-core`) for
settings, logging, DB base, models, ledger engine, and storage backends.

**Why:** the plan's `packages/` lists only TS packages, but api/worker/bot all
need the same models and ledger invariants; duplicating them would drift.
The plan itself defers exact packaging to an integration spike.

**Revisit when:** the queue-technology prototype (PostgreSQL-backed vs Redis)
settles the deployment story.

## D2 — SQLite as the zero-dependency local database

**Decision:** `XP_DATABASE_URL` defaults to SQLite (aiosqlite) locally;
Postgres is the target for regtest+ environments via docker-compose.

**Why:** phase 1 acceptance says a developer starts the system from docs with
no production secrets; SQLite keeps that honest and fast. Portable column
types (String UUIDs, JSON, no dialect locks) keep migrations identical.

**Revisit when:** regtest environment work begins (phase 3).

## D3 — Queue: arq (Redis) with inline dev fallback

**Decision:** arq worker over Redis in shared environments; when Redis is not
configured the API executes the same job function inline in a thread.

**Why:** preserves the worker boundary and job semantics without forcing
infrastructure on day one. The plan explicitly defers Redis-vs-Postgres queue
to an operational prototype.

**Revisit when:** reliability tests measure retry/timeouts under load.

## D4 — Agent runtime: controlled adapter, stub-first

**Decision:** `services/agent-adapter` is the only model surface. DeepSeek is
reached via the OpenAI-compatible API; the upstream DSH integration is behind
`XP_DSH_REVISION` (currently unpinned) and tools are allowlisted/typed.

**Why:** the plan requires pinning a tested DSH revision after a spike; until
that spike, stub mode keeps CI hermetic and prevents accidental coupling.

**Revisit when:** phase-0 DSH integration spike completes (pin revision,
document lifecycle + error handling).

## D5 — Wallet & Lightning: protocols now, libraries later

**Decision:** `WalletProvider` / `LightningProvider` protocols + regtest
stubs + explicit `SigningBoundary`. No library chosen yet.

**Why:** the plan mandates a documented threat-model and integration spike
before committing to a wallet/Lightning implementation, and requires adapters
stay replaceable so the choice never leaks through the codebase.

**Revisit when:** phase-3 spikes evaluate BDK/bitcoind and LDK/CLN/lnd.

## D6 — Nuxt in SPA mode for the Mini App

**Decision:** `ssr: false` for the Mini App.

**Why:** Mini Apps run inside Telegram's webview; SSR adds auth/session
complexity with no UX benefit there. Server-side rendering can be revisited
for public marketing pages later.

## D7 — What is deliberately NOT done yet (honesty list)

- No wallet key handling of any kind (phase 3 + release gates).
- No Lightning node connectivity (phase 3+ after channel-state review).
- No real web-search provider behind `web.search` stub (phase 4).
- No payment provider settlement verification (phase 4 XP purchases).
- Dev grants exist ONLY under DEV_MODE and are audit-logged.
- ~~Telegram session revocation hardening~~ — delivered in phase 2 (short-lived sessions, server-side logout/revoke, lifecycle UI).

## D8 — DSH "upstream" = pinned DeepSeek API surface, not a package

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
pricing, thinking-mode guide) showed the drift risk is in the API surface —
our original scaffold default `deepseek-chat` had already been discontinued
upstream. A manifest pin captures exactly the facts that can break us and
keeps the adapter the only place that knows them.

**Consequences:** re-pinning is a deliberate two-step (manifest + checksum
test) plus `make dsh-verify` live proof; no import-time coupling to any
harness package. Revisit if a canonical DSH package appears or if DeepSeek
ships an incompatible wire-format change.

## D9 — Short-lived sessions + server-side revocation model

**Decision:** bearer sessions live 24h (`XP_SESSION_TTL_HOURS`, down from 14
days), are stored as SHA-256 hashes, and all lifecycle actions are
server-authoritative: `POST /auth/logout` revokes the presented token,
`GET /auth/sessions` lists live sessions, `DELETE /auth/sessions/{id}`
revokes one by id with strict ownership (foreign ids return the same 404 as
missing ones — no oracle). A throttled `last_used_at` heartbeat (5-min
window) powers the visibility UI without write amplification.

**Why:** phase-2 acceptance demands "forged or expired payloads rejected"
and the trust boundary demands "short-lived sessions"; the Mini App
re-exchanges fresh initData on every launch, so a short TTL costs nothing
in UX. Client-side token dropping alone (the scaffold's logout) left
stolen tokens valid for weeks — unacceptable for a product whose threat
model includes Telegram-account compromise.

**Consequences:** the settings screen gains a real "Active sessions"
surface; expired/revoked tokens return 401 on every endpoint via the shared
dependency. Logout requires a bearer token even in DEV_MODE so clients
cannot mistake "cleared local copy" for "revoked server-side".

## D10 — BDK (bdkpython) for the on-chain wallet; bitcoind RPC as the chain source

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
  built from **public descriptors only** — tests assert the on-disk bytes
  contain no mnemonic material and no `xprv`/`tprv` strings.
- Signing happens in an **in-memory private wallet** built at unlock from the
  user's recovery phrase; the phrase lives in process memory for the unlock
  TTL (`XP_WALLET_UNLOCK_TTL_MINUTES`, default 10) and is dropped on
  lock/expiry. The persisted (public) wallet owns the UTXO graph and builds
  the PSBT; the unlocked private wallet signs it — proven by the offline
  funding tests, which run the two-wallet flow without any chain source.
- The signing boundary rejects agent actors unconditionally and binds every
  signature to an authorization digest over the reviewed transaction fields
  (destination, amount, fee, network). Validation failures do not consume the
  prepared transaction (no DoS-by-retry); only a completed signature does.
- Address aliases are labels: `prepare` resolves an alias once, the digest
  binds the resolved address, and relabeling cannot redirect an existing
  prepared transaction (tested).
- Broadcast failures are explicit: definite rejections (502) vs. node
  unreachable during send (504, "outcome unknown — resolve by txid").
- Mainnet is hard-gated in the provider constructor pending the security
  review release gate.

**Consequences:** regtest needs no electrs/esplora — chain data enters the
wallet graph via `import_transaction` (bring-your-own-chain-source), which is
also the documented seam for a full Electrum/Esplora sync later. The API
restart story is honest: `reopen()` restores graph/balance state from public
descriptors alone; signing always requires a fresh unlock. This is a
server-side signing-vault build — docs and UI must not claim non-custodial
or browser-side signing until those phases land.

## D11 — Lightning: lnd v0.21.4-beta selected via empirical drill; canned semantics provider for offline-proofable lifecycles (2026-10-15, phase 4)

**Context:** the plan requires a selected Lightning implementation, invoice
and payment lifecycles, fee preview + authorization, channel-state backup and
recovery drills, health/liquidity disclosure, and duplicate-callback-safe
accounting — with regtest integration tests for the chosen implementation.

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
family) — on rpcpolling AND with a healthy loopback zmq probe, mined
outputs are never credited, so live channel funding cannot complete
in-sandbox. The drill reproduces cleanly: stages 1 (chain), 2 (two nodes
ACTIVE), 7 (restart + unlock) PASS; stages 3–6 and 8 report BLOCKED with
diagnostics instead of pretending. Instead of faking it, the phase ships:
(a) the real gRPC adapter, (b) a canned provider with lnd-identical
semantics (clocked expiry, preimage-bound settlement, digest-bound
authorization, checksummed SCB) that makes every lifecycle/idempotency
acceptance criterion testable offline, (c) the drill script as the re-run
instrument for a healthy host.

**Consequences:** settlement idempotency is enforced by a CAS status
transition plus the ledger's idempotency key — duplicate callbacks are
structurally incapable of double-crediting (tested with six repeats). Fee
authorization binds the digest of what was shown; wrong digest → 409.
Mainnet stays refused at provider construction (same release gate as D10).
The canned provider is disclosed verbatim in `/lightning/capabilities` —
not pretending a real node exists when it does not.

## D12 — One canonical conversion (`xp_per_sat`); receipts as derived views (2026-10-15, phase 5)

**Context:** the scaffold carried two contradictory rates (`sats_per_xp=10`
for display, `xp_per_sat=100` for actual crediting) — exactly the kind of
drift the plan's pricing_requirements ("publish the conversion") exists to
prevent. Separately, receipts could be modeled as a new table or as views.

**Decision:** `xp_per_sat` is the single published conversion; credits are
always `sats × xp_per_sat` computed at settle time. Receipts are derived
views over `(payment_intent, xp_ledger_entry)` — no receipt table — and the
PDF receipt renders from DB rows only. Reconciliation runs as a scheduled
worker job plus a dev-seam endpoint, checking (a) balance == sum(entries)
per user, (b) settled receive intents ↔ purchase entries 1:1, (c) expired
pending liveness, and audits every flag.

**Consequences:** display surfaces (bot, Mini App, shared types) changed
wire shape (`BalanceOut.xp_per_sat`); the contract cannot drift again
because there is nothing left to drift — one setting, one computation site.
A receipt can never contradict the ledger because it is the ledger viewed,
not a copy.

## D13 — `task_events` as the 17th table; DB-checked approval and cancel (2026-10-15, phase 6)

**Context:** the plan's 16-table model predates the "task event stream and
progress updates" deliverable. The event stream could be squeezed into
`task_steps` or `audit_events`, or its own table.

**Decision:** add `task_events` (append-only, `(task_id, seq)` unique) as a
documented deviation: steps are state (current step status), events are
history (ordered, replayable, includes approvals/evaluation/outcomes) —
different consumers, different retention. Approval decisions and
cancellation are enforced DB-side: the runner re-reads committed state
(`approvals.status` for the exact action digest; `tasks.status` between
steps), so worker restarts and cross-process cancels are safe without
in-memory coordination.

**Consequences:** 17 tables now (migration `e5f6a7b8c9d0`); `audit_events`
stays minimal (digest-level tool facts), `task_events` carries the replay
stream with shape-level payloads (no raw tool output), keeping the stream
inspectable without leaking untrusted content into every consumer.

## D14 — Research tools: canned-search honesty, SSRF-walled fetch, provenance in the DB, quality gates in backend code (2026-10-15, phase 7)

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
labels itself as such on every response — an honest offline equivalent, not
a fake live web. Fetch has two transports: the same canned corpus, and a
real httpx provider behind `FetchPolicy` (http/https only, ports 80/443,
no userinfo, localhost/reserved hostnames denied, every resolved IP must be
globally routable — DNS rebinding fails closed, redirects re-pass the full
wall per hop, size + content-type caps). Provenance persists in an 18th
table, `research_sources`, keyed `(task, url)`: search listings start
`listed`, fetches upgrade to `ok`, and unavailable/denied/errored fetches
are KEPT as first-class records and disclosed — never silently dropped.
Facts are typed observed|estimate|assumption; price figures from listing
snapshots are typed `estimate` with a staleness note, so no listing price
can masquerade as a live quote. The report builder in the API assembles a
`ReportSpec` from durable rows; `xp_core.services.documents` enforces the
quality gates (every claim cited, every citation resolvable, duplicate-free
sources) and REFUSES to render violations, then validates generated files
by magic bytes/structure before private storage. The tool handlers return
shape only (ids, counts, fact keys) to the model — page content never
enters agent context raw.

**Consequences:** 18 tables (migration `a9b0c1d2e3f4`); `docs.generate_pdf`
in the product registry is real (the phase-6 stub plan cost math is
preserved, so the golden-path settlement is unchanged); the evaluation set
(`tests/data/research_eval_set.json` + `make research-eval`) makes the
quality bars a repeatable regression harness with 5 cases covering
citations, conflicts, unavailable disclosure, estimate typing, and the
honest-empty report. Live search awaits a search API key (tracked open
item); live fetch works wherever the sandbox has egress.

## D15 — Commerce intelligence: structural-only scoring, canned ad-library honesty, typed landed-cost template (2026-10-15, phase 8)

**Context:** phase 8 asks for product discovery, supported ad-library
integrations, trend scoring with transparent signals, supplier/listing
comparison, vehicle auction research, a landed-cost estimate template, and
source freshness/confidence indicators — under acceptance bars that forbid
inventing demand, ad-performance, or availability claims, and require
visible, configurable scoring factors.

**Decision:** a dedicated `services/commerce-adapter` package over the same
provenance records phase 7 persists (no new tables — verdicts live in
`task_events`, artifacts in `artifacts`). Scoring exposes EXACTLY five
structural factors (`distinct_sources`, `supplier_count`, `price_spread`,
`freshness`, `attribute_completeness`) with operator-configured weights
(`XP_COMMERCE_SCORING_FACTORS`); the weight configuration is echoed verbatim
in every verdict, any config defect falls back to documented defaults WITH a
disclosure, and factors with insufficient data are excluded with reasons
instead of silently zeroed. There is deliberately NO demand, ad-performance,
or availability factor — the platform cannot measure those from snapshot
pages. The ad-library integration is canned-only and says so on every
result; page-printed performance metrics stay in provenance but never enter
a summary or a score. The landed-cost template types every line
(asking price = estimate, official published rate = observed, user input =
assumption), states that no verified transaction cost exists in the
pipeline, and — when the model binds a source — takes the line VALUE from
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

## D16 — Email + automation: preview-before-send, digest-bound expiring approvals, encrypted credential vault, budget-laddered scheduler (2026-10-15, phase 9)

**Context:** phase 9 asks for an external service connection framework, scoped
credential storage, email draft/preview, explicit send approval, scheduled
jobs, condition-based notifications, pause/resume/cancel/failure handling,
and run history — under five acceptance bars: valid authorization + approved
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
   credential row — a revoked connection cannot authenticate even if other
   layers were bypassed. Dev mode may use a documented fallback key that is
   DISCLOSED on every surface; non-dev environments refuse to link without
   an operator key (`XP_CONNECTIONS_CREDENTIAL_KEY`).
2. **Email flow.** `email.draft` persists a draft with a content digest;
   `email.send` executes only post-approval, only for an UNSNT draft whose
   content matches the approved digest, and only against a linked
   connection with the `email:send` scope. Providers implement an honest
   taxonomy: `sent` / `refused` (definite, safe to report) / `unknown`
   (transport failed mid-session — the server may have accepted the
   message; the system records `unknown_outcome`, discloses it loudly, and
   NEVER auto-retries — mirroring the phase-3 wallet broadcast taxonomy).
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
   >= 60s, `daily HH:MM` UTC, `hourly`, `daily`) — full cron is a documented
   non-goal for this phase. Each run's task budget is
   `min(budget_per_run_xp, remaining_total)`; the ledger's cap refusal makes
   the per-run limit hold end-to-end, and an affordability pre-check records
   the skip cleanly without touching the ledger. Total budget exhausted ->
   run skipped AND job auto-paused with a notification. Consecutive failures
   (operator-configured ladder, default 3) auto-pause + notify. Every
   attempt — success, failure, skip, block — is an `AutomationRun` row.
5. **Consequential-action discipline.** A run whose spawned task awaits
   approval blocks (`blocked_on_approval`); subsequent sweeps WAIT — no new
   task, no new approval spam, no hidden resend. A denied approval fails the
   task explicitly with full reservation release. A worker crash mid-run is
   recovered by a staleness window (run marked failed, failure ladder
   applies); fresher runs are waited on, never run concurrently.
6. **Scope stacking.** `email:send` and `automation:write` join
   USER_TASK_SCOPES (they were structurally unreachable stubs before), and
   their tools still carry `requires_approval=True` — the scope wall and
   the approval gate stack; untrusted content cannot bypass either.

**Rejected alternatives:** storing credentials as environment variables per
user (unscalable, unauditable); auto-retrying email on unknown outcomes
(could double-send — the exact acceptance violation); full cron parsing
(dep-heavy, easy to get DST/timezone wrong silently); silently ignoring
unknown condition keys (typo -> job that never notifies looks healthy);
resuming a denied-approval task (would re-request approval forever).

**Consequences:** notifications are persisted + API-readable with Telegram
relay as an open item (pretending to push without a bot token would
fabricate delivery). Live SMTP delivery needs a real server + an operator
master key; everything else is fully testable offline. The automation sweep
runs in the worker cron (arq) and inline in dev; one broken job never kills
a sweep (per-job error isolation with logged outcomes).
