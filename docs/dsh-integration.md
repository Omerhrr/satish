# DSH Integration Contract

**Pinned revision:** `dsh-pin-2026-10-15-flash-v4-1`
**Manifest:** `services/agent-adapter/dsh_adapter/dsh_revision.json` (sha256-gated by `tests/test_dsh_revision.py`)
**Status:** phase-0 spike complete - contract tests offline (53 passing incl. 21 spike tests); live proof pending an API key via `make dsh-verify`.

This document is the integration contract required by the plan
(`agent_and_tooling.dsh_integration.requirements` #2: "Document startup,
configuration, supported tool interface, event lifecycle, and error
handling"). Everything DSH-specific lives behind
`services/agent-adapter/dsh_adapter/`; no other module may import an
OpenAI SDK or talk to the model runtime directly (requirement #3).

## 1. What "upstream" means here - an honesty note

The plan describes DSH as "a separately maintained upstream component."
Researching the upstream landscape on 2026-10-15 found **no canonical,
importable open-source package named "DeepSeek Harness"** that could be
pinned as a dependency or submodule. What actually exists and is pinned is
**DeepSeek's hosted API surface** (OpenAI-compatible Chat Completions at
`https://api.deepseek.com`). The pin therefore binds the *wire surface and
model revisions*, which is the piece that can silently drift:

| Pinned fact | Value | Verified from |
|---|---|---|
| Primary model | `deepseek-flash` → DeepSeek-V4.1-Flash (2026-09-10) | Change Log 2026-09-10 |
| Heavy model | `deepseek-v4-pro` → DeepSeek-V4-Pro-0813 | Models & Pricing |
| Base URL | `https://api.deepseek.com` | Models & Pricing |
| Thinking mode | ON by default, effort=high; toggle `extra_body.thinking.type` | Thinking Mode guide |
| Sampling params | inert (thinking) / fixed 1.0 (non-thinking) - not sent | Thinking Mode guide |
| Legacy `deepseek-chat` / `deepseek-reasoner` | discontinued 2026-07-24 - **rejected by the adapter** | Change Log |
| Context / max output | 1M / 384K | Models & Pricing |
| Flash pricing (per 1M) | in $0.15-0.30 (cache-hit $0.003-0.006), out $0.60-1.20 | Models & Pricing |

The spike decision (docs/decisions.md **D8**) records why a manifest pin was
chosen over a submodule/dependency pin.

## 2. Startup

```
XP_DEEPSEEK_API_KEY set?
├─ yes → DeepSeekChatClient(model=None ⇒ pin primary, base_url=None ⇒ pin base_url)
│        └─ validate_model(): discontinued alias ⇒ RevisionError (fail-loud startup)
└─ no  → StubChatClient (deterministic offline mode; whole system testable)
```

- `make_chat_client(settings)` is the only construction point.
- The manifest is loaded and structurally validated at client construction
  (`revision.load_revision`); a malformed manifest aborts startup.
- `XP_DEEPSEEK_MODEL` may override the model, but must be a pinned model or
  a retired-but-served alias; **discontinued aliases fail loudly**.

## 3. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `XP_DEEPSEEK_API_KEY` | unset → stub mode | Bearer credential; never logged |
| `XP_DEEPSEEK_MODEL` | None ⇒ `deepseek-flash` | Override validated against the pin |
| `XP_DEEPSEEK_BASE_URL` | None ⇒ pin value | For tests/proxies only |

Adapter limits come from the manifest (`adapter_contract.adapter_limits`):
timeout 60 s · 2 retries · 0.5 s exponential backoff base · 4 concurrent
requests · 20 000-char output cap · 2048 max tokens for planning.

## 4. Supported tool interface

Tools are declared as typed `ToolSpec`s in the allowlisted
`ToolRegistry` (`tools.py`) and exposed to the model as OpenAI function
definitions. The registry enforces, per call:

- **category allowlist** (research, commerce_intelligence, documents,
  communication, automation),
- **required scope** granted per run by the application,
- **required arguments** validation,
- **XP budget check** (`max_cost_xp`) before execution,
- **approval flag** → the adapter suspends and asks the application
  (`on_approval_required`) instead of acting,
- **timeouts** per tool (`timeout_seconds`, default 30 s).

Requirement #5 ("expose only tools needed for the current product and user
authorization") is satisfied by construction: nothing is reachable that is
not registered, and nothing is registered that is not in an allowlisted
category with an explicit scope.

## 5. Event lifecycle

`PlanRunner` (`runner.py`) implements the plan's agent execution contract:

```
goal → draft_plan (model, non-thinking) → on_plan(persisted)
     → per step: budget check → approval gate (if flagged)
                → registry.execute → on_step(running|completed|rejected|denied|
                  invalid_arguments|awaiting_approval|skipped|cancelled)
     → on_complete(report)
```

- Durable state lives in the **application database** via the injected
  `PersistenceHooks` - never in transient model context (requirement #4).
- **Cancellation:** `runner.cancel()` sets a cooperative flag checked
  between steps; the run returns `status="cancelled"` with a partial report.
- The model response's `reasoning_content` (thinking mode) is **never
  persisted or fed back**; the adapter records only its character count.
- Retrieved/untrusted content is wrapped in
  `<<<UNTRUSTED_CONTENT_BEGIN/END>>>` markers so injection is visible.

## 6. Error handling

| Condition | Behaviour |
|---|---|
| Transient upstream (408/429/5xx, timeout, connection) | bounded retry: 2 retries, exponential backoff + jitter |
| Permanent 4xx | raised immediately (retrying would be dishonest noise) |
| Retries exhausted | last exception propagates; `on_step` already recorded `running` so the task is resumable |
| Malformed model JSON | safe empty plan, reported as limitation |
| Discontinued model name | `LegacyModelError` at startup - never a silent fallback |
| Manifest drift | sha256 checksum gate in tests fails CI |

## 7. Cost tracking (requirement #8)

- Every model call records usage into `runner.model_usage`:
  prompt/completion/cache-hit tokens + `estimated_cost_usd` computed from
  **pinned pricing** (off-peak). Unpriced models yield `None` + an explicit
  `cost_note` - never a silent zero.
- Every tool call's XP cost accrues into `spent_xp` against the reserved
  budget (existing XP ledger integration).
- Summaries appear in `on_plan` payloads and the final report
  (`report.model_usage`).

## 8. Re-pinning procedure (upgrade path)

1. Fetch current facts: change log, Models & Pricing, Thinking Mode guide.
2. Edit `dsh_revision.json` (models, limits, pricing, legacy aliases, `revision_id`, `pinned_at`).
3. Run `pytest tests/test_dsh_revision.py` - the checksum gate fails; update
   `EXPECTED_MANIFEST_SHA256` **in the same change** (conscious, reviewable).
4. Run `make dsh-verify XP_DEEPSEEK_API_KEY=…` - live proof on the new pin.
5. Record the change in `docs/decisions.md`.

## 9. Open items (honest)

- Live `make dsh-verify` has not run in this environment (no API key); the
  contract suite (21 tests) is the current proof. Run before any release gate.
- JSON Output mode (`response_format: json_object`) is intentionally not set
  while tools are attached (interaction unverified); planning relies on
  prompt-level JSON instructions + safe parsing.
- Off-peak pricing is used for estimates; peak/off-peak windows are not
  scheduled in code.
