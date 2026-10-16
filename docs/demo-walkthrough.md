# Demo Walkthrough (phase 11)

Two ways to see XP work: the **one-command API demo** (`make demo`, fully
reproducible) and the **interactive Mini App tour** (running services, your
browser). This document is the script for both - and for recording a video
walkthrough, since none is committed (a recording from a repo that changes
weekly would go stale and silently lie; the script below cannot).

## A. `make demo` - expected transcript

```text
XP end-to-end demo - fresh in-memory DB, zero external services
  [1] health: status=ok, database=ok, env=dev
  [2] session: mode=dev, ttl=24h, token_issued=True
  [3] xp_grant: balance=2000
  [4] wallet_create: provider=canned/regtest-offline, words=24,
      first_address=bcrt1q…, seed_stored_server_side=False
  [5] purchase: pack=1000sats, invoice=lntb1…, xp_preview=100000, status=pending
  [6] settlement: credited=True, replay_credited=False,
      double_credit_possible=False, ledger_entry=ab12cd34…, balance_after=102000
  [7] task_created: id=…, budget_xp=500, reserved=500
  [8] agent_run: engine=DSH stub (no API key configured - disclosed), status=completed
  [9] task_result: deliverable=True, limitations=1, xp_receipt=True
  [10] artifact_pdf: bytes=13618, magic=%PDF-, private_storage=True, owner_checked=True
  [11] ops: open_critical=0, open_warning=0, rate_limit_enabled=True, env=dev
  note: Wallet/Lightning providers here are the canned, deterministic ones; …
  note: The settlement path IS the production code path (CAS + ledger
        idempotency + 1:1 reconciliation) - replay refusal is structural.
  note: Real-Bitcoin proofs are separate committed drills: make wallet-regtest,
        make lightning-drill (need a healthy host).
  note: The agent ran in stub mode because no DeepSeek key is configured; …
DEMO PASSED (11 steps verified)
```

What to point at while narrating:

1. Step 4 - the seed phrase is displayed ONCE and the server stores only a
   public descriptor (`tprv` absent). This is the custody model.
2. Step 6 - settle, then replay the SAME settlement: the second attempt
   reports `credited=False`. Double-crediting is structurally impossible
   (CAS + idempotency key + 1:1 reconciliation), not merely discouraged.
3. Step 8 - the agent discloses its own stub mode. When a DeepSeek key is
   configured the same task runs through the pinned-revision live client;
   the tool wall and approval gates are identical.
4. Step 10 - a real WeasyPrint-rendered PDF served from private storage
   through an owner-checked download.

## B. Interactive Mini App tour (services running)

```bash
make migrate && make run-api &   # API on :8001
make run-web                     # Mini App on :3000
```

Script (each step matches a screen):

1. **Console** (`/`): live health cards; "Seed +1,000 XP" - the ledger page
   updates and the balance reconciles visibly.
2. **XP** (`/xp`): the append-only ledger - every entry typed
   (adjustment/reserve/purchase/refund), balances derived from entries.
3. **Tasks** (`/tasks`): create a task with a budget; watch the atomic
   reservation; cancel it and watch the release (or let it run and settle).
4. **Wallet** (`/wallet`): the custody disclosure - what the server stores
   (public descriptors), what it never stores (seeds), what the agent may
   never do (sign).
5. **Billing** (`/billing`): published packs and the canonical
   conversion - clients must re-check, never cache.
6. **Connections / Automations**: preview-before-send email flows and the
   budget-laddered scheduler with its honest pause/refuse taxonomy.
7. **Settings** (`/settings`): session lifecycle (24h, revoke, last-used),
   recovery guidance, and the phase-10 custody/data/retention card.

## C. Recording a walkthrough video (maintainer script)

1. Clean checkout + `make demo` (record terminal, ~60s).
2. `make run-api && make run-web`, walk screens B1-B7 (~4 min).
3. `make wallet-regtest` on a regtest host - the real-Bitcoin segment
   (~2 min; this is the part that proves the money claims on actual
   Bitcoin test infrastructure).
4. Close with `docs/known-limitations.md` on screen - the project's
   honesty register is part of the pitch, not a footnote.

Publish the video unlisted with a pinned comment linking the exact commit;
re-record on major phase bumps rather than letting footage drift.
