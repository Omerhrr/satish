# Roadmap — implemented vs. planned (phase 11)

Status per plan phase; "implemented" means code + tests + docs are
committed and green (266 tests). Every planned item's absence is honest —
see `docs/known-limitations.md` for the instrument that closes each gap.

| # | Phase | Status | Evidence |
| --- | --- | --- | --- |
| 0 | Product definition, DSH pinning spike | **Implemented** | D8, `dsh_revision.json` + drift gate, 21 spike tests. Live verify pending key (KL-01) |
| 1 | Repository & developer foundation | **Implemented** | Monorepo, 23-table model, migrations, CI-config (parked: KL-14), docs |
| 2 | Telegram identity & Mini App | **Implemented** | initData HMAC, 24h sessions, revocation, session UI; 14 bot commands; 8 Mini App screens. Replay-window tuning open (KL-13) |
| 3 | On-chain self-custody wallet | **Implemented** | BDK provider, regtest proof suite, public-descriptor-only persistence, digest-bound signing flow, alias-redirect refusal |
| 4 | Lightning wallet | **Implemented** | lnd v0.21.4-beta (ADR D11), canned/real twin state machines, preimage-bound settlement (6x replay test), fee caps, SCB roundtrip. Live drill needs host (KL-02/KL-03) |
| 5 | XP ledger & payment conversion | **Implemented** | One canonical `xp_per_sat`, packs, purchase/receipt flow, reconciliation job, budget caps |
| 6 | DeepSeek Harness integration | **Implemented** | Durable agent runtime: task_events, DB-checked approvals, scope wall, budget-aware dispatch, resume. Live model runs pending key (KL-01) |
| 7 | Research & deliverable tools | **Implemented** | SSRF wall, provenance table, cross-source comparison, quality gates, PDF/CSV/XLSX artifacts, committed eval set (`make research-eval`) |
| 8 | Commerce intelligence | **Implemented** | Structural-only scoring with echoed weights, typed facts (no fabricated costs), supplier/listing comparison, committed eval set (`make commerce-eval`). Live ad-library connector open (KL-08) |
| 9 | Email & automation workflows | **Implemented** | Fernet credential vault, preview-before-send, digest+TTL approvals, budget-laddered scheduler, notification queue. Telegram relay open (KL-06) |
| 10 | Security, reliability, ops readiness | **Implemented** | Rate limiting, reconciliation alerts (23rd table), retention sweep + policy, backup/restore drill, dependency/container audit, IR runbooks, security review + limitations register. Postgres/SCB restore rehearsal + multi-process rate limits open (KL-04/05/09) |
| 11 | Open-source release & Btrust package | **Implemented** | This release package: demo (`make demo`), walkthrough, disclosure policy, contributing guide, roadmap, Btrust proposal, limitations register |

## Planned next (post-plan, tracked honestly)

- **KL-01**: run `make dsh-verify` with a real DeepSeek key; then flip the
  agent from stub to live behind the same tool wall.
- **KL-02/03/05**: run `make lightning-drill` + SCB restore rehearsal on a
  healthy host; document evidence in the drill doc.
- **KL-04**: rehearse pg_dump/pg_restore + verification gates against a real
  Postgres instance.
- **KL-06**: Telegram relay for notifications (bot token configured path).
- **KL-09**: Redis-backed rate-limit bucket backend for multi-worker
  deployments; validation-joined per-user subjects.
- **KL-10**: self-serve account closure/export with ledger-aware erasure.
- **KL-11**: operator identity model in front of `/ops/*` before any
  non-dev deployment.
- **KL-14**: merge the parked CI workflows (`backup-with-ci` branch) once a
  `workflow`-scoped token is available; add license review.
- **KL-15**: independent external security review — the release gate for
  real-value production use.
