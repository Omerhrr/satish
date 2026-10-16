# Btrust Technical Proposal - XP: a Bitcoin-native AI workforce (phase 11)

*Audience: Btrust (BitMEX founder Arthur Hayes' bitcoin-focused grant
program) reviewers and any funder evaluating Bitcoin utility projects.*

## 1. The Bitcoin utility thesis

AI assistance is rapidly becoming a purchasable commodity - research,
document drafting, monitoring, and approved automation. Today that
commodity is sold through custodial intermediaries: card processors,
subscription rails, and platforms that hold the user's money (and data)
until the service is consumed. That model fails three ways for
Bitcoin-native users: it excludes people who hold sats rather than cards,
it re-introduces custodial risk for money that users deliberately hold
self-custodially, and it gives the AI platform irreversible control over
both payment and execution.

XP's answer is to make **Bitcoin the settlement layer and self-custody the
default**: users pay for work in sats over Lightning and on-chain, the
application credits (XP) are an append-only ledger derived from verified
payments, and the user's keys never leave the user. The platform can be
evaluated, operated, and abandoned without anyone granting maintainers
custody of funds - that is a deliberate acceptance criterion of the plan
and it is testable today (`make demo`, `make wallet-regtest`).

## 2. Target users

- **Bitcoin-holding individuals** who want AI labor (research, vehicle and
  product intelligence, document generation, approved email/automation)
  without opening a custodial account anywhere.
- **Telegram communities** in regions where Telegram is the primary
  internet surface - the Mini App + bot pattern meets users where they
  already are, with no app-store gatekeeper.
- **Operators of small AI-work businesses** who need auditable,
  budget-capped agent execution with human approval gates - not an
  autonomous agent with a blank check.
- **Open-source auditors and funders** who need every claim in this
  document to be reproducible from the repository, not taken on faith.

## 3. Architecture (summary)

- **Telegram is the interface, never a key vault.** Identity is a
  Telegram initData HMAC exchange producing 24-hour server-side sessions
  with revocation; the bot cannot ask for seeds and the UI cannot paste
  them anywhere.
- **Self-custody wallets** via BDK with public-descriptor-only persistence;
  the signing vault is rebuilt in memory from the user's phrase at unlock
  and expires with inactivity. Lightning runs on lnd v0.21.4-beta behind an
  adapter protocol with a deterministic canned twin for hermetic testing.
- **XP economy**: one published sats→XP conversion; purchases become
  payment intents; settlement is verified through a double gate
  (preimage-hash binding + CAS row transition + ledger idempotency key)
  proven structurally incapable of double-crediting (6x replay tests).
- **Agent execution** (DeepSeek via a pinned-revision DSH adapter) is
  budget-capped, tool-allowlisted, scope-walled, approval-gated for
  consequential actions, and fully event-audited. Untrusted web content is
  wrapped so prompt injection cannot reach authorization.
- **Operational readiness**: rate limiting, reconciliation alert queue
  with operator lifecycle, daily retention sweep that structurally cannot
  touch money/audit trails, backup/restore drills, dependency audits, and
  incident runbooks (R1-R6).

Full detail: `docs/architecture.md`, `docs/threat-model.md`,
`docs/decisions.md` (D1-D17).

## 4. Security posture (summary)

Threat-model-driven from phase 0: assets, adversaries, and mitigations are
written down, then tests pin each mitigation (initData forgery, scope-wall
bypass attempts, SSRF hops, settlement replay, credential-vault paths).
The current build's known gaps are registered publicly (KL-01…KL-15), and
the one unresolved release-gate item - **independent external security
review** - is explicitly marked as pending rather than implied (KL-15).
No uncompleted feature is represented as production-ready anywhere in the
documentation, and canned/offline surfaces label themselves at the API
layer, not just in prose.

## 5. Open-source maintenance plan

- **Repository**: single open-source monorepo (permissive license to be
  finalized with the phase-0 license review; no proprietary holdbacks
  exist in the tree), conventional commits per phase, every phase's
  acceptance criteria traceable to tests and docs.
- **Quality gates**: `make test` (266 cases), `make lint`,
  `make audit` (dependency/container pin gates), `make backup-drill`,
  `make demo` (end-to-end golden path) - all runnable by a new contributor
  in under ten minutes with zero external services.
- **Honesty as governance**: the known-limitations register and the
  roadmap's implemented/planned split are part of the review surface; PRs
  that overclaim are treated as defects, matching the project's core
  principle that a wallet's trustworthiness is only as good as its
  accuracy about itself.
- **Maintainership**: initial ownership map in `CONTRIBUTING.md`
  (maintainer: @Omerhrr; module owners listed per area). External
  contributions flow through the same quality gates; security reports via
  `SECURITY.md` (responsible disclosure, 90-day window).
- **What funding would accelerate**: the pending live proofs (DeepSeek key,
  lnd drill host, Postgres restore rehearsal), the Redis-backed multi-worker
  rate-limit backend, the operator identity layer for `/ops`, the
  independent security review, and the Telegram notification relay - each
  already scoped in `docs/roadmap.md`.

## 6. Why this is evaluable without custody

Every dollar-equivalent flow can be exercised on regtest
(`make wallet-regtest`, `make lightning-drill`) or on the canned twin
(`make demo`) without mainnet funds, without a custodial account, and
without giving maintainers anything but public repository access. The
wallet model has no server-side secret fields by construction - the data
model itself is the audit.
