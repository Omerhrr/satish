# XP economy — ledger, pricing, purchases, reconciliation (phase 5)

Status: implemented. Tests: `tests/test_xp_economy.py` (23) + ledger
invariants in `tests/test_ledger.py`.

## The one conversion

**`xp_per_sat`** (env `XP_XP_PER_SAT`, default `100`) is the single source of
truth: XP credited = `sats × xp_per_sat`, computed at settle time. The
former `sats_per_xp=10` setting contradicted it and was removed; every
surface (rate endpoint, balance, bot, Mini App) now derives its display
from the one rate. The rate is **published with `can_change: true`** —
clients must re-check `GET /api/v1/xp/rate`, never cache (pricing
requirement #1).

## Billing flow (plan mapping)

| Plan step | Implementation |
|---|---|
| User chooses a pack or enters an amount | `GET /xp/packs` (published table from `XP_XP_PACK_SATS`) or custom `amount_sats`; `POST /xp/purchases` |
| Backend creates unique intent + invoice | `PaymentIntent` (receive direction) + bolt11 via the lightning service |
| User reviews and pays | Mini App billing page; wallet pays the invoice |
| Backend independently verifies settlement | `lightning_service.settle` double gate: preimage hashes to payment_hash → CAS row transition → ledger credit |
| Idempotent credit | `credit_purchase` keyed `purchase:{intent_id}` — replays return `credited: false` |
| Receipt + updated balance | `GET /xp/purchases/{id}` (binds the ledger entry) + `POST /xp/purchases/{id}/receipt.pdf` (WeasyPrint artifact) |
| Scheduled reconciliation | worker cron (`XP_RECONCILE_INTERVAL_SECONDS`) + `POST /xp/reconcile` (dev seam) |

Receipts are **derived views** over `(payment_intent, xp_ledger_entry)` —
not a new table — so a receipt can never disagree with the ledger. The PDF
is rendered from DB rows only.

## Ledger invariants → enforcement

- Every mutation in a DB transaction — all ledger calls take the session.
- Every purchase tied to one verified settled payment — settle gate.
- A payment credited once — CAS row + unique idempotency key; reconciliation
  additionally flags any settled intent without exactly one entry and any
  entry without a settled intent.
- Concurrent reservations cannot overdraw — CAS `UPDATE ... WHERE
  balance + delta >= 0`; proven by the 8-way concurrent test (exactly 5 of
  8 win against a 500 balance).
- Refunds/corrections append — `refund`/`adjust` are new entries.
- Balance == sum(entries) — `reconcile_all` sweep (users, orphans,
  settlement integrity, expired-pending liveness) + audit event per flag.

## Task charge flow → enforcement (acceptance #6)

- Budget reserved atomically at task creation (`reserve:{task_id}`).
- **A task cannot exceed its approved budget without additional
  authorization**: settlement refuses `actual > budget` before anything is
  written (`POST /tasks/{id}/settle` → 409; ledger double-checks).
- Additional authorization = `POST /tasks/{id}/increase-budget` — a USER
  route that reserves the delta under `reserve:inc:{task_id}:{new_total}`
  and audits `task.budget_increased`. The agent registry has no path to it
  (test-enforced).
- Failed/cancelled tasks release the FULL unused reservation
  (`task_service.fail_task` / cancel) — auditable, never a history rewrite.

## Pre-task estimate

`POST /tasks/estimate` returns a deterministic heuristic range plus the
variable-cost activity list (search, fetch, PDF render, model tokens). The
agent plan (phase 6) finalizes the estimate; the heuristic keeps the UI
honest before any model call.

## API surface added

- `GET /api/v1/xp/rate` — published conversion (xp_per_sat, can_change).
- `GET /api/v1/xp/packs` — the pack table.
- `POST|GET /api/v1/xp/purchases`, `GET /api/v1/xp/purchases/{id}` — plan
  api_contract's XP purchase group; receipts bind the ledger entry.
- `POST /api/v1/xp/purchases/{id}/receipt.pdf` — receipt artifact (409
  unless settled).
- `POST /api/v1/xp/reconcile` — reconciliation sweep (dev seam).
- `POST /api/v1/tasks/estimate|{id}/increase-budget|{id}/settle`.
- `POST /api/v1/lightning/invoices/{hash}/settle-dev` — DEV_MODE+canned-only
  auto-settle so the Mini App can drive the whole flow without touching
  preimages.

## Open items

- lnd-mode settlement is the node's invoice-settled stream (phase-4 open
  item); the settle gate is unchanged — the stream supplies the preimage.
- No user-facing XP→sats refund path (self-custody sats are not held by the
  platform; failed tasks refund the XP reservation instead).
