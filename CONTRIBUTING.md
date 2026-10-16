# Contributing to XP

Thanks for looking at XP. The project's core engineering principle is
**honesty about what is real**: every claim of a working feature must be
reproducible from this repository, and every gap must be visible in
`docs/known-limitations.md`. A PR that overclaims is a defect, same as a
broken test.

## Getting set up (10 minutes, zero external services)

```bash
cd xp
python3 -m venv .venv && .venv/bin/pip install -U pip
uv pip install --python .venv/bin/python -e packages/py-core -e services/api \
  -e services/worker -e services/agent-adapter -e services/wallet-adapter \
  -e services/lightning-adapter -e services/research-adapter \
  -e services/commerce-adapter -e services/email-adapter -e apps/bot
bun install
make migrate && make demo   # proves your env end-to-end
```

## The quality bars (CI-parity, run locally)

| Gate | Command | Bar |
| --- | --- | --- |
| Tests | `make test` | full suite green, no skips added casually |
| Lint | `make lint` | ruff clean |
| Audit | `make audit` | no unpinnable dependency specs or `:latest` images |
| Drill | `make backup-drill` | restore roundtrip + re-reconciliation holds |
| Demo | `make demo` | golden path passes end-to-end |
| Web | `cd apps/web && bun run build` | Nuxt build clean |
| Migrations | alembic `upgrade head` + `downgrade base` + `upgrade head` | roundtrip clean |

## Ground rules

1. **Money surfaces are sacred.** Anything touching the XP ledger, payment
   intents, or settlement must keep: append-only entries, CAS balance
   transitions, idempotency keys, and the 1:1 intent↔entry invariant.
   Reconciliation alerts that are `critical` must never be auto-resolved.
2. **Honesty at the API layer.** Canned/deterministic providers must label
   themselves in their responses. No surface may fabricate delivery,
   settlement, or capability that is not configured (this is what
   "can_change"/"not_claimed" disclosures mean).
3. **New dependencies** need a reason in the PR description and a pinned
   spec; the audit gate will reject `*`, `git+`, and `:latest`.
4. **Security-relevant changes** (auth, scopes, approvals, wallet,
   Lightning, credentials) need a test that pins the mitigation they touch,
   and a look at `docs/threat-model.md` - update it if the boundary moves.
5. **Schema changes** go through Alembic with a roundtrip-verified
   migration and a docstring explaining the phase/decision.
6. **Docs move with code.** If your change alters behavior described in
   `docs/*.md`, update the doc in the same PR. The known-limitations
   register is part of the review surface.

## Code ownership

| Area | Path | Owner |
| --- | --- | --- |
| Ledger / economy | `packages/py-core/xp_core/{models,services/jobs}`, `services/api` xp/tasks | @Omerhrr |
| Wallet / Lightning | `services/wallet-adapter`, `services/lightning-adapter` | @Omerhrr |
| Agent / DSH | `services/agent-adapter`, `services/worker` agent jobs | @Omerhrr |
| API surface | `services/api/app` | @Omerhrr |
| Mini App | `apps/web` | @Omerhrr |
| Docs / threat model | `docs/` | @Omerhrr |

(Project is young: single maintainer with explicit intent to broaden
ownership per-module as contributors establish history. Btrust-funded
work expands this map in the open.)

## Commit style

One logical change per commit, message states what and why; phase-scale
changes get the full evidence trail in the message (tests count, migration
id, gates run) matching the existing history.

## Reporting issues

Security: `SECURITY.md` (responsible disclosure, 90-day window).
Everything else: GitHub issues with reproduction steps; if it touches a
drill or the demo, attach the failing step's transcript.
