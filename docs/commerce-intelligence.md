# Commerce intelligence and vehicle research (phase 8)

Phase 8 turns the phase-7 research pipeline into commerce tooling:
product discovery, supplier/listing comparison, vehicle auction research,
transparent trend scoring, a landed-cost estimate template, and source
freshness/confidence indicators — under four acceptance bars that are
enforced by deterministic backend code, not by the model's goodwill:

1. **Only accessible and permitted sources are represented as searched.**
   Search and fetch run through the SAME phase-7 permission wall
   (`FetchPolicy` for http, committed fixtures for canned). The ad-library
   integration is canned-only and says so verbatim on every result; a query
   with no fixture returns zero results plus a disclosure — never filler.
2. **The report distinguishes asking prices, estimates, and verified
   costs.** Commerce fact typing (`commerce_adapter.classify`): asking
   prices from market/auction/dealer listings are `estimate` ("asking price
   snapshot, not a live quote"); supplier quotations are `estimate` ("not a
   verified cost"); figures from OFFICIAL sources (tariff/fee schedules)
   are `observed` ("official published rate"). Verified transaction costs
   do not exist in this pipeline, and the landed-cost output says so
   explicitly.
3. **No unsupported demand, ad-performance, or availability claims are
   invented.** Scoring has no demand/performance/availability factor by
   construction; page-printed performance metrics (CTR, impressions...) and
   availability claims stay untrusted provenance and never enter a summary
   or a score — with an explicit disclosure when present.
4. **Scoring factors are visible and configurable.** Weights come from
   `XP_COMMERCE_SCORING_FACTORS` (operator-configured JSON); every verdict
   echoes the configuration, every factor shows its raw signal, normalized
   value, weight, and inclusion reason, and any config defect falls back to
   the documented defaults WITH a disclosure.

## Architecture

`services/commerce-adapter/commerce_adapter/` (pure, deterministic):

| module | role |
|---|---|
| `classify.py` | commerce fact typing per source type (supplier / market / auction / dealer / official / ad_library); performance + availability key registries |
| `scoring.py` | factor table, weight config parsing (fallback-with-disclosure), candidate selection, per-factor verdicts, weight-normalized 0–100 score |
| `suppliers.py` | supplier vs listing vs official comparison with [S{n}] citations, conflicts, gaps, disclosures |
| `vehicles.py` | vehicle/auction sources checked against explicit specs (exact + bound rules); mismatches are cited facts |
| `adlibrary.py` | canned ad-library provider + ad attribute summarizer (performance excluded) |
| `landed.py` | typed landed-cost template with refusals, not guesses |
| `freshness.py` | freshness labels (fresh/recent/stale/outdated) + confidence (status + retrieval mode + corroboration, capped at 0.9) |
| `eval.py` | the committed evaluation-set runner |

`services/api/app/services/commerce_tools.py` registers six tools on the
product registry (same scope wall, budget gate, audit path; category
`commerce_intelligence`, scope `research:read`):

| tool | cost | what it does |
|---|---|---|
| `commerce.compare_suppliers` | 4 | cited supplier/listing/official comparison; persists `commerce.suppliers_compared` |
| `commerce.score` | 5 | transparent structural scoring; persists `commerce.scored` (factor table + config echo) |
| `commerce.vehicle_check` | 3 | specs vs fetched vehicle sources; persists `commerce.vehicle.checked` |
| `commerce.landed_cost` | 2 | typed landed-cost estimate; persists `commerce.landed_cost.computed` |
| `commerce.ad_library_search` | 4 | canned ad-library search; persists listed rows + `commerce.ad_library.searched` |
| `commerce.fetch_ad` | 2 | fetch an ad fixture: attributes summarized, performance excluded |

Commerce fixture pages join the SAME canned corpus (`web.search` /
`web.fetch_page` reach them unchanged); their `source_type` is persisted in
the source note so commerce tools classify roles deterministically. No new
tables: verdicts live in `task_events`, files in `artifacts`.

## Scoring factors (defaults)

| factor | default weight | signal | normalization |
|---|---|---|---|
| `distinct_sources` | 2.0 | fetched sources carrying the candidate | count / 3, capped at 1 |
| `supplier_count` | 1.5 | distinct supplier quotations | count / 2, capped at 1 |
| `price_spread` | 1.5 | asking-price spread (same currency only) | 1 − min(spread / 0.5, 1) |
| `freshness` | 1.0 | retrieval freshness mix | mean of fresh=1 recent=0.66 stale=0.33 outdated=0 |
| `attribute_completeness` | 1.0 | required attributes present | covered / required |

Insufficient data (one price, mixed currencies, no required-keys list) →
the factor is EXCLUDED with a reason; the score is the weight-normalized
mean over included factors only, so absence is never silently scored as 0.

## Landed-cost template

Every line carries value + kind + basis (+ citation when bound):
asking price → `estimate`; duty bound to an official schedule → `observed`;
shipping/insurance/fees → `assumption`. When the model binds a source id
(`unit_price_source_id` / `duty_source_id`), the line VALUE comes from the
persisted fact — citing [S2] with a different number is structurally
impossible — and foreign/unparseable bindings are refused. The output
discloses: "landed cost is an ESTIMATE ... not a quotation" and "no
verified transaction cost exists in this pipeline".

## Result surface

`GET /tasks/{id}/result` now carries per-source `freshness` and
`confidence` labels, plus the latest `commerce.scored` verdict (`scored`
block: product, score, factor table, config echo, disclosures). The Mini
App task page renders both.

## Evaluation set

`tests/data/commerce_eval_set.json` — 8 offline fixture pages (2 supplier
quotations, an official tariff, an ad-library page with a deliberately
poisoned CTR line, an auction lot, a dealer listing, USD + GHS market
listings), 7 cases: scoring transparency/config, mixed-currency exclusion,
supplier conflicts, ad-library no-performance + honest zero results,
vehicle spec checks, landed-cost typing. `make commerce-eval` must stay
7/7 — it is the regression harness for the honesty guarantees.

## Honest open items

- Live ad-library integration needs a permitted API partnership (no
  scraping of login-walled libraries, ever); canned fixtures stand in and
  are labeled.
- Live search still awaits a search API key (phase-7 open item); commerce
  search is canned over the committed corpora.
- Currency conversion is deliberately absent: mixed-currency comparisons
  are excluded rather than converted with an invented rate.
