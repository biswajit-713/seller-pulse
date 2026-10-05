# Synthetic Queries

Twenty-six query / expected-answer pairs for evaluating the SellerPulse agent, in
[`queries.jsonl`](queries.jsonl) (one JSON object per line).

Every expected answer is grounded in the repo's own input data — `data/listings.csv`,
`data/reviews.csv`, `data/sales.csv` and `data/policy/seller_policy_handbook.md`. Nothing
here is invented: each record carries a `references` array pointing at the exact rows,
review IDs or policy chunk that produces the answer, together with the computed value, so a
grader can re-derive the number instead of trusting it.

## Record schema

| Field | Meaning |
|---|---|
| `id` | `SQ-01` … `SQ-26` |
| `query` | what Meera types |
| `query_context` | optional — content pasted alongside the query (only `SQ-03`, the review being replied to) |
| `intent` | `tool_analytics`, `tool_inventory`, `tool_order_issues`, `tool_analytics_plus_inventory`, `tool_inventory_plus_policy`, `rag_listing_plus_tool`, `rag_reviews`, `rag_reviews_coverage`, `rag_policy`, `memory_write`, `memory_update`, `draft_generation`, `draft_generation_internal`, `guardrail_policy_refusal`, `guardrail_no_fabricated_numbers`, `tool_analytics_degraded`, `tool_failure_degraded` |
| `covers_sample_query` | the row number in `docs/requirements.md` §3 this reproduces, else `null` |
| `expected_behavior` | what the agent must *do* — which tool, draft labeling, refusal shape |
| `expected_answer` | the grounded content the answer must contain |
| `references` | `{source, locator, value}` — where to look in the input data to validate |
| `guardrails` | which `docs/requirements.md` §5 rules the case exercises |
| `notes` | ambiguity, accepted alternate anchorings, fixtures not to "fix" |

## Coverage

`SQ-01` … `SQ-06` are the six sample queries from `docs/requirements.md` §3, in order and
verbatim — `covers_sample_query` carries the §3 row number, and is `null` for the rest. The
only wording difference is `SQ-03`, whose "this 2-star review" needs a referent: the query
string stays verbatim and the pasted review lives in `query_context`.

The remaining twenty extend into cases the six leave untested:

- **Tools / analytics** — `SQ-08` (metric ambiguity: units vs revenue), `SQ-09` (partial
  month), `SQ-11` (category aggregation), `SQ-17` (no data for the requested day),
  `SQ-26` (slow movers holding stock).
- **Inventory + policy** — `SQ-07` (zero stock, still Active), `SQ-21` (order issues
  visible only as buyer complaints, with no orders table behind them).
- **RAG over reviews** — `SQ-12` (complaint themes), `SQ-13` (worst-rated, tiny samples),
  `SQ-19` (the 65 SKUs with no reviews).
- **RAG over policy** — `SQ-15` (conditional answer, not yes/no).
- **Guardrails** — `SQ-10` (refuse to forecast), `SQ-14` (keyword stuffing), `SQ-18`
  (compensation for a rating change), `SQ-20` (deceptive strike-through price),
  `SQ-25` (unsubstantiated material and delivery claims).
- **Memory** — `SQ-16` (reply tone, must survive into later sessions), `SQ-22` (changing a
  stored threshold without silently overriding it).
- **Drafts** — `SQ-23` (internal restock reminder — the approval gate is scoped to
  customer-facing output and must not be over-applied).
- **Failure handling** — `SQ-24` (inventory tool times out).

Three pairs are deliberate A/B contrasts and should be graded together: `SQ-04`/`SQ-24`
(same query, tool works vs times out), `SQ-03`/`SQ-23` (customer-facing draft vs internal
note), and `SQ-05`/`SQ-22` (threshold set, then changed).

## Agent eval cases

[`agent_cases.jsonl`](agent_cases.jsonl) drives the live end-to-end agent eval
(`plan/ev-00-overview.md`). Like `retrieval_cases.jsonl`, each line points at a query by
`source_query` and never copies its text — `query`, `query_context`, `expected_behavior`,
`expected_answer` and `notes` are joined from `queries.jsonl` at load time.

| Field | Meaning |
|---|---|
| `id` | `AE-01` … `AE-18` |
| `source_query` | the `SQ-` id in `queries.jsonl` |
| `status` | `scored` (counts toward the 80% threshold) or `known_gap` (runs and is reported, not scored) |
| `bucket` | `sales` \| `guardrail` \| `rag_draft` — for per-bucket rates |
| `checks` | deterministic checks — see below; empty means judge-only, and `why` says so |
| `traceable_allow` | optional — values legitimately absent from every source, each with a `why` |
| `why` | one line: what the case proves (for `known_gap`, the missing capability) |

Check kinds: `tool_called` (≥1 call to `name`; each listed `args` value must be in its accepted
list), `no_tool_called` (`name`, or any tool if omitted, never called), `contains_all` (every
needle in the answer), `contains_any` (at least one `groups` entry present in full — for
accepted alternate anchorings), `not_contains_pattern` (regex must not match). Each check
scores one dimension — `tool_use`, `accuracy` or `grounded` — defaulting by kind
(`tool_*` → `tool_use`, `contains_*` → `accuracy`, `not_contains_pattern` → `grounded`),
overridable with `"dimension"`. The fourth dimension, `behavior`, is judge-only. An automatic
`traceable` check (every ID and number in the answer must appear in the tool trace, retrieved
context or query) runs on every case and is never written here.

Every figure or ID needle comes from its query's `expected_answer` or `references`.

## Anchoring

The data runs `2026-08-03` → `2026-09-25`; the assistant "today" assumed throughout is
`2026-09-27`. Relative-time queries (`SQ-01` "last week", `SQ-17` "yesterday") state the
absolute window in the expected answer, and `SQ-01` lists the trailing-7-day figures (the
tool's `last_7_days`, `2026-09-20..09-26`, 6 of 7 days recorded) as an accepted alternate
reading.

## Deliberate fixtures

`SQ-07` depends on SKU-1013 and SKU-1020 carrying `stock_qty 0` with `status: Active`. That
inconsistency is intentional — see the data note in `CLAUDE.md` and `plan/01-data-fix.md`.
Normalizing it would silently delete the test case.

`SQ-02` and `SQ-19` depend on "Boho Wall Hanging" matching three SKUs (1001, 1011, 1021) of
which only 1001 has reviews, per `plan/rag-10-corpus-coverage.md`.

## Regenerating

The figures were computed directly from the CSVs. To re-derive any of them, group
`data/sales.csv` by the `locator` given in that record's `references` entry — every sales
row satisfies `revenue_usd == units_sold * listings.price_usd`, so no price history is
implied anywhere in the set.
