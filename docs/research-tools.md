# Research and deliverable tools (phase 7)

The agent's research pipeline: search → permitted fetch → extraction →
provenance → cross-source comparison → cited, validated artifacts — with
quality gates enforced by deterministic backend code.

## Architecture

```
services/research-adapter/research_adapter/   (adapter boundary — no DB)
  policy.py      FetchPolicy: the permission wall for page retrieval
  providers.py   SearchProvider / FetchProvider: canned + http transports
  extract.py     stdlib HTML→text/facts extraction (deterministic)
  provenance.py  SourceRecord / Fact typing (observed|estimate|assumption)
  compare.py     cross-source comparison: rows, conflicts, gaps, disclosures
  eval.py        the repeatable research evaluation set runner

packages/py-core/xp_core/services/documents.py  (pure render + gates)
  ReportSpec + check_report_spec (quality gates)
  render_report_pdf / build_csv / build_xlsx / validate_document

services/api/app/services/research_tools.py    (product registry)
  real tool handlers wired to the agent runtime + application DB
```

## Tools (product registry)

| Tool | Scope | Cost | What it does |
|---|---|---|---|
| `web.search` | `research:read` | 5 XP | canned provider over the eval corpus; listings persist as `listed` sources |
| `web.fetch_page` | `research:read` | 2 XP | policy-gated fetch; facts typed + persisted; model gets shape only |
| `research.compare` | `research:read` | 3 XP | conflicts / gaps / disclosures; persists a `research.compared` event |
| `docs.generate_pdf` | `documents:write` | 10 XP | cited report; quality gates; validated PDF; private artifact |
| `docs.generate_csv` | `documents:write` | 6 XP | cited comparison table → validated CSV |
| `docs.generate_xlsx` | `documents:write` | 6 XP | cited comparison table → validated XLSX |

The model never sees raw page content: handlers return ids, counts, fact
keys, and honest disclosure strings. Content lives in `research_sources`
and is treated as untrusted data end to end.

## Permission model (page retrieval)

`FetchPolicy` denies, in order: non-http(s) schemes, userinfo URLs,
non-80/443 ports, localhost/`*.local`/`*.internal` names, non-global
IP-literals; then, after DNS resolution, EVERY address must be globally
routable (one private answer denies the whole host — rebinding fails
closed); each redirect hop re-passes the full wall; bodies are capped
(256 KB default) and only `text/*` / `application/json` are accepted.
Retrieved content is wrapped as untrusted downstream (phase-6 contract).

## Provenance model

`research_sources` (18th table, migration `a9b0c1d2e3f4`) is
`(task, url)`-unique: refetching upgrades a row (a later failure never
downgrades a successful fetch). Statuses: `listed | ok | unavailable |
denied | error`. Facts carry `kind`:

- `observed` — stated by the fetched page
- `estimate` — price-ish keys from a listing snapshot, with a staleness
  note ("retrieved at T, not a live quote")
- `assumption` — reserved for model-supplied context (not produced by tools)

## Report quality checks (backend-enforced)

`check_report_spec` refuses to render when: a claim has no citation, a
citation points at an unknown source, source indices duplicate, or claims
exist with an empty source list. `docs.generate_pdf` returns a structured
`quality_gate_failed` result instead of an artifact. Generated files are
validated (`%PDF-` + `%%EOF`, CSV width/parse round-trip, XLSX zip +
workbook.xml) BEFORE storage, and storage is private-by-default —
downloads go through the owner-checked
`GET /api/v1/artifacts/{id}/download` only.

## Explicit result, limitations, XP receipt

`GET /api/v1/tasks/{id}/result` (phase-7 acceptance #4) returns the
deliverable, validated artifacts with sha256, full source provenance,
conflicts + gaps from the latest `research.compared` verdict, limitations
(evaluation notes + disclosures + unreachable sources), and the XP receipt
derived from the ledger trail (budget / charged / released / entry id /
balance after).

## Repeatable evaluation set

`tests/data/research_eval_set.json` holds an offline corpus (5 pages,
`.test` hosts) and 5 cases covering: citations + estimate typing,
cross-source conflict detection, unavailable-source + gap disclosure,
stale-listing-never-live, and the honest empty report. Every case runs the
full workflow and must render a valid, fully-cited PDF.

```bash
make research-eval          # exit 0 iff all cases pass
python scripts/research_eval.py [path/to/set.json]
```

The set is also asserted from pytest (`tests/test_research_eval.py`), so a
pipeline regression fails CI-style before anything ships.

## Honest status / open items

- **Search is canned-only.** A live search adapter needs a search API key
  (Brave/Bing/etc.) — none is configured, and canned output is labeled as
  such on every response rather than pretending to be live web.
- **Live fetch** (`XP_RESEARCH_FETCH_MODE=http`) is fully implemented and
  unit-tested via MockTransport; egress from this sandbox may be limited.
- Reports reflect retrieval-time snapshots; the structural gates verify
  citations and disclosure, not factual truth — sources remain the user's
  responsibility to review (stated in every report's Limitations box).
