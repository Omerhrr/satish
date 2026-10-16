# Security Review (phase 10)

**Scope**: full internal review of the security-relevant surface as of
phase-9 (`2e8a514`) plus the phase-10 additions (rate limiting,
reconciliation alerts, retention sweep, drill/audit tooling).

**Status - read this first**: this is a *structured internal* review by the
implementing agent. It is thorough, evidence-linked, and reproducible - but
it is **not** an independent review. Phase-10's own deliverable
("Independent security review") therefore remains **open** as KL-15, and
"No known critical findings remain unresolved before real-value production
use" is evaluated against the register below with that caveat stated
plainly.

## Method

1. Inventory every trust boundary (docs/threat-model.md) and walk each
   phase's acceptance criteria against tests.
2. For each security-relevant module: read the code path end-to-end, then
   find the test that pins the behavior. Un-tested security claims are
   findings by definition.
3. Re-verify the invariant stack: ledger CAS + idempotency + 1:1
   settlement, scope wall, approval digests, SSRF wall, credential vault
   single-path decryption.

## Verified strengths (evidence)

- **Money integrity**: settle-time CAS + ledger idempotency key + the
  reconciliation 1:1 check; 6x replay tests in tests/test_xp_economy.py;
  phase-10 adds a persisted alert queue that cannot silently close critical
  findings (tests/test_phase10_ops.py).
- **Authorization**: USER_TASK_SCOPES scope wall evaluated before approval
  gates; approval digests bind to exact content; untrusted-content wrappers
  cannot reach tools directly.
- **Identity**: initData HMAC with auth_date validation (forgery/stale/
  wrong-token tests); 24h sessions; server-side revocation; per-session
  last_used heartbeat.
- **Network egress**: FetchPolicy SSRF wall (scheme/port/private-IP/
  per-hop) - tests pin each bypass attempt.
- **Secrets at rest**: wallet stores public descriptors only; connection
  credentials Fernet-encrypted with a single decryption path; no seed or
  private-key fields exist in any model (structural).
- **Abuse controls (new)**: route-class token buckets with honest 429s,
  kill switch, monitoring surfaces exempt; suite-verified.

## Findings register

| ID | Sev | Finding | Status |
| --- | --- | --- | --- |
| F-01 | high→fixed | Rate limiting absent entirely (pre-phase-10): auth/money/agent endpoints had no abuse ceiling | **Fixed** in phase 10 (middleware + tests); per-process scope residual **closed** with the Redis backend (D20, KL-09) |
| F-02 | medium | Payment discrepancies were audit-log-only - an operator watching logs could miss drift | **Fixed**: persisted dedupe alert queue + ack/resolve lifecycle + observability counts |
| F-03 | medium | `/ops/*` gated by DEV_MODE flag only; no operator identity model | **Accepted for now** (KL-11); must be closed before any non-dev deployment |
| F-04 | medium | No automated dependency/vulnerability gate | **Mitigated**: `make audit` inventory + hard-spec gates committed; live CVE scanning (pip-audit/trivy) documented as operator CI step - scanner absence is disclosed, never faked |
| F-05 | low→fixed | Bearer-fingerprint rate-limit subject allows bucket refresh via token rotation | **Fixed** (D20): validated bearers join per-user limiter keys via the identity cache; rotation of one user's tokens drains one bucket. Cold-join first request accepted (see threat-model residual) |
| F-06 | low | Retention windows are settings, not code-constants - a misconfiguration could over-delete | Mitigated: PRESERVED_SURFACES is structural (money/audit never swept regardless of settings); window tests pin behavior |
| F-07 | low | Backup drill covers SQLite logical roundtrip only | Accepted (KL-04/KL-05); drill prints its own scope notes so nobody mistakes it for a Postgres/SCB proof |

No critical findings remain open in this build. The two high-severity
items found during review (F-01) were fixed in this phase with tests.

## Independent review - what it must cover (for the reviewer)

1. Reproduce the money-integrity stack (ledger invariants, replay tests).
2. Attempt scope-wall bypasses via untrusted content in tool inputs.
3. Audit the FetchPolicy wall against a hostile redirect chain.
4. Verify the credential vault's single decryption path and revocation.
5. Assess rate-limit fitness for the target deployment topology.
6. Own the "production readiness" call - this document deliberately does
   not make it.
