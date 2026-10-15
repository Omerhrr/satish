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
