# Agent runtime - durable DSH task execution (phase 6)

Status: implemented. Tests: `tests/test_agent_runtime.py` (16).

## Architecture

```
POST /tasks (reserve budget)
POST /tasks/{id}/run  ──►  arq queue ──►  worker/jobs/agent.py
   (inline dev bridge when no Redis)          │
                                              ▼
                              app/services/agent_service.py
                    PlanRunner + DbPersistenceHooks (application DB)
                                              │
                    dsh_adapter: pinned revision → ChatClient → ToolRegistry
```

All durable state lives in the application database (`tasks`, `task_steps`,
`task_events`, `approvals`); the runner instance holds nothing that matters.
A killed worker loses nothing: the next run rebuilds from the DB.

## State machine

Task: `planned → running → completed | failed | cancelled`, with
`awaiting_approval` pausing mid-run when a tool requires user approval.
Cancel is durable: the endpoint flips `tasks.status`; the runner re-reads it
between steps and stops, releasing the untouched reservation.

## Execution loop (PlanRunner)

1. **Plan** - model call (non-thinking per pin) returns JSON steps; each
   step becomes a `task_steps` row + `plan.created` event.
2. **Per step** - deterministic gates in order:
   registry knows the tool → **scope wall** (server-side `USER_TASK_SCOPES`,
   never content-derived) → **budget** (`max_cost_xp ≤ remaining`) →
   **approval** (DB-checked, digest-bound) → **hard timeout** (`asyncio.wait_for`
   on the spec timeout) → execute.
3. **Settle** - `ledger.settle_task(reserved, actual=min(spent, budget))`;
   the ledger refuses anything above the approved cap.
4. **Evaluate** - deterministic structural evaluation (completeness /
   provenance / consistency) persisted as an event; never a model verdict.

## Acceptance criteria → mechanisms

| Criterion | Mechanism | Test |
|---|---|---|
| DSH cannot access private key material | registry has no wallet/sign/seed tools; system policy forbids; wallet provider rejects agent actors | `test_registry_has_no_key_material` (+ phase-3 suite) |
| Agent requests cannot bypass user authorization | approval-required tools pause; decision is a USER endpoint on the digest-bound `approvals` row; no budget-mutation tool exists | `test_approval_gate_*`, `test_registry_has_no_budget_mutation_tool` |
| Tool outputs and task states persist across restarts | steps/events/approvals in DB, hooks commit per step, resume skips completed steps | `test_state_survives_restart_and_resume` |
| Untrusted web content cannot expand tool permissions | scopes are server-side constants; scope wall runs BEFORE approval; untrusted content wrapped in UNTRUSTED markers | `test_untrusted_content_cannot_expand_scopes` |
| Budget limits and tool timeouts enforced by deterministic backend code | registry wait_for timeout; budget gate; ledger cap on settlement | `test_tool_timeout_*`, `test_budget_dispatch_*`, `test_over_budget_settlement_refused_at_ledger` |

## Event stream

`task_events` (append-only, `(task_id, seq)` unique): `task.started`,
`plan.created`, `step.running|completed|denied|rejected|timeout|cancelled`,
`approval.requested|approved|denied|reused`, `evaluation.completed`,
`task.completed|failed|cancelled`. `GET /tasks/{id}/events` replays it;
`GET /tasks/{id}/steps` shows the durable step table. Payloads carry shape
(status, keys) rather than raw tool output - the stream stays inspectable
without becoming an untrusted-content channel.

## Audit records

Every terminal tool call writes `audit_events(actor_type="agent",
event_type="tool.call", resource_id=tool)` with task/step/status only -
never argument values or output text.

## Approvals

`on_approval_required` checks the DB for an `approved` row with the SAME
`action_digest` (sha256 of canonical `{tool, args}`); a hit resumes
transparently, a miss creates a `pending` row and stops the run. The user
decides via `POST /tasks/{id}/approvals/{id}/decision`. A denied digest
never executes; changing the arguments changes the digest (no blanket
consent).

## Scope policy

`USER_TASK_SCOPES = {research:read, documents:write, email:draft}`.
`email.send` / `automation.schedule` are additionally approval-gated and
arrive with their product surfaces in later phases. A denied tool costs 0
XP and the run still settles honestly.

## Cost tracking

Per model call usage lands in `model_usage` (tokens + cache hits +
`estimated_cost_usd` from pinned pricing) and is reported in the
`task.completed` event and the report. Unknown pricing yields an explicit
cost note, never a silent zero.

## Stub mode

Without `XP_DEEPSEEK_API_KEY` the client is deterministic (plan:
web.search → docs.generate_pdf with valid arguments), so the full loop -
reservation, execution, events, evaluation, settlement - is testable and
demoable offline.

## Open items

- `make dsh-verify` live proof still awaits a DeepSeek key.
- Model-judged evaluation (beyond structural) lands with real research
  tools (phase 7); the evaluator interface already persists the verdict.
