# SellerPulse: 4-Week Task Plan
*Core path: 34 one-hour tasks; this is the safe, required build every team should be able to finish. Stretch Goals (bottom) are optional add-ons for teams with extra time.*

## Current state (as of 2026-10-17)

Week 1 (tasks 1–11) is done, including task 1 (`docs/team.md`). Week 2 (tasks 12–18) is closed
out, with two items open: #17's unprompted recall fails and #18 still needs its screenshot.
Built: the `docs/tools.md` spec, `sales.py:get_sales_analytics`,
`inventory.py:check_inventory_status`, LangChain wrappers in `tools.py`, the async tool loop in
`agent.py`, a system prompt that requires tool-sourced figures (`prompts.py`), an MCP server
(`mcp_server.py`) the app loads its tools from over stdio (`mcp_tools.py`), the seller
preference store and its tools (`memory.py`, `docs/memory.md`), preferences recalled into every
turn, and an "Agent trace" panel in the UI (`trace_view.py`). pytest: 268 passed; retrieval eval
10/10. Close-out walkthrough: `docs/verification.md`, "Week 2 close-out".
Weeks 3–4 are not started, except #27/#28 (agent eval, pulled forward). Status is tracked per
task in the tables below; a finer-grained, file-level breakdown lives in `plan/STATUS.md`
(gitignored, local only).

## Week 1: Foundations, RAG & UI (11 tasks)
**Demo Goal:** A live Gradio chat UI that answers a seller's performance question with a RAG-grounded diagnosis of a specific listing; no tools, memory, or guardrails yet, but it's clickable and shareable. Plus two written deliverables: an Amazon-style 6-pager and a PR/FAQ.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion | Status |
|---|---|---|---|---|
| 1 | Kickoff: assign roles, review requirements.md and Meera Iyer's persona/objective, agree on tech stack | Roles assigned (prompt/RAG, tools/MCP, memory, guardrails/caching, observability/UI owners); requirements.md read by everyone; stack agreed | A `docs/team.md` listing roles and stack, with each member confirming they've read requirements.md | Done |
| 2 | Write an Amazon-style 6-pager for SellerPulse: narrative memo covering the problem, the customer (Meera), the solution, goals & non-goals, key risks/mitigations, and success metrics | 6-pager committed as a narrative document (no slides/bullets-only sections); every section from the standard format is present and specific to SellerPulse, not generic | `docs/6-pager.md` in repo, reviewed and agreed on by the whole team | Done |
| 3 | Write a PR/FAQ for SellerPulse: a mock press release announcing the launch, plus an FAQ covering customer questions and internal/guardrail questions | PR/FAQ committed; press release is written from the customer's (Meera's) point of view; FAQ has at least 5 questions, including at least one on data handling and one on guardrails/policy compliance | `docs/pr-faq.md` in repo, reviewed and agreed on by the whole team | Done — committed as `docs/pr-faq_1.md` |
| 4 | Set up the git repository: initialize repo, agree on branch strategy, add .gitignore, write a README | Repo exists remotely with main + feature branches; README lets a fresh clone run the project | A teammate clones the repo and runs it successfully from README alone | Done |
| 5 | Draft the system prompt: seller-engagement tone, "never invent a number" rule, draft-only output rule | Prompt file committed; 2 manual test prompts confirm figures are only ever tool-sourced and outputs are labeled as drafts | `src/seller_pulse/prompts.py` + `docs/verification.md` §B (SQ-06, SQ-03 transcripts) and §C.6 (sales/inventory/best-seller abstention, the stronger "tool-sourced-only" evidence) | Done — DoD as written needs tools, which don't exist yet in Week 1; satisfied instead via abstention transcripts |
| 6 | Generate a synthetic dataset of a seller's listings, sales history, inventory levels, orders, and reviews | Dataset file committed covering ~150 SKUs with several weeks of sales/order history | Dataset file in repo + a summary count of listings/orders/reviews | Done |
| 7 | Prepare the RAG corpus: listing content, past reviews, and marketplace seller-policy documents | Corpus covers all 6 sample queries in requirements.md, especially the underperforming-listing diagnosis and the policy-violation case | Corpus files committed with item/document count | Done |
| 8 | Build the ingestion pipeline: chunk and embed the corpus into a vector store | Pipeline runs with no errors; vector store has the expected chunk count | Console log showing chunk/embedding count | Done |
| 9 | Implement retrieval and test against "why is my Boho Wall Hanging listing underperforming?" | Relevant listing/review chunk(s) appear in the top-3 retrieved results | **Scope note:** the Boho Wall Hanging / SQ-02 case needs `resolve_listings()` and sales data, deferred to the SQ-02 increment (`plan/rag-05-listings-domain.md`); delivered instead against the five queries `policy_kb`/`seller_reviews` alone can answer. `uv run python -m seller_pulse.evals.retrieval_eval` (10/10, exit 0) + `docs/retrieval.md`'s measured scores + `docs/verification.md` | Done (scoped) — 10/10 on the five answerable queries; Boho Wall Hanging/SQ-02 deferred |
| 10 | Wire a minimal prototype: seller question → grounded diagnosis (no tools yet) | Full query→diagnosis round trip runs without crashing and reflects the corpus data | Terminal/notebook transcript of one successful run | Done |
| 11 | Build a Gradio chat UI for the prototype and deploy it locally with a shareable link | Gradio app launches and returns a grounded diagnosis for a real query | Screenshot of the running UI + shareable link posted to the team channel | Done |

## Week 2: Tools, MCP & Memory (7 tasks)
**Demo Goal:** The same Gradio UI now pulls live sales/inventory figures and drafts a review reply, and remembers the seller's notification preferences across two visits; visible live in the chat.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion | Status |
|---|---|---|---|---|
| 12 | Design tool specs: `get_sales_analytics(seller_id, period)` and `check_inventory_status(sku)` | Written spec for both tools: inputs, outputs, error cases | `docs/tools.md` with both signatures and example input/output | Done |
| 13 | Implement the sales-analytics tool | Returns correct revenue/units/orders for a known period and a clear error for an invalid one | Test log showing both cases | Done — `tests/test_period.py` + `tests/test_sales_analytics.py` (SQ-01/SQ-17 figures); live in chat since the agent-loop wiring, served over MCP (task 15) |
| 14 | Implement the inventory-status tool | Returns correct stock level for a known SKU and a clear error for an unknown one | Test log showing both cases | Done — `tests/test_inventory_status.py` + `tests/test_tools.py` (LangChain wrapper); MCP exposure is task 15 |
| 15 | Set up MCP to expose both tools to the agent; test a full round trip | Agent calls both tools via MCP and uses their results in a live response | Trace/log of one query showing the response built from tool output | Done — `mcp_server.py` (FastMCP, stdio) + `mcp_tools.py:load_mcp_tools` (`langchain-mcp-adapters`); app loads both tools over MCP. Live trace 2026-10-14: "How did last week go, and how much SKU-1001 stock is left?" → both MCP tool calls logged, answer 904 units / $41,904.71 / 6 in stock. Tests: `tests/test_mcp_server.py`, `tests/test_mcp_tools.py` |
| 16 | Design the memory schema: notification cadence, reply tone, and restock threshold preferences | Schema documented; a record can be written and read back correctly | Schema doc + log of one record written and retrieved | Done — `docs/memory.md` (schema + cross-process write/read log), `memory.py:PreferenceStore`, `tests/test_memory_store.py` |
| 17 | Integrate memory; test preference recall (e.g., "notify me every Friday about low best-sellers") across 2 sessions | Preference stated in session 1 is correctly recalled, unprompted, in session 2 | Transcripts of both sessions showing the preference and its recall | In progress — DoD not met. Persistence across restarts verified twice (`docs/verification.md`, "Week 2 — two-session memory verification" and "Week 2 close-out"), and stored preferences are applied in later sessions (threshold 3 used on a stock lookup, tone used on a draft). Unprompted recall of the Friday cadence fails: the prompt surfaces it only "if relevant to today" and `TODAY` (2026-09-27) is a Sunday. Fix is a product call, listed in the verification follow-ups |
| 18 | Wire tools and memory into the Gradio UI via an expandable "agent trace" panel | Panel lists each tool call and the recalled preferences for the response | Screenshot of the panel expanded on a real query | Code done, screenshot pending — `trace_view.py` + the "Agent trace" accordion in `app.py`; `tests/test_trace_view.py`. The panel text for four live queries is in `docs/verification.md`, "Week 2 close-out". The DoD screenshot of the expanded panel in the browser has not been taken |

## Week 3: Guardrails & Caching (7 tasks)
**Demo Goal:** In the live UI, show the agent refuse a review-manipulation request and label a review-reply draft as pending approval, and show a visible speed-up (cache hit badge) on a repeated analytics query.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion | Status |
|---|---|---|---|---|
| 19 | Codify guardrail rules: no fabricated figures, no auto-publishing, no policy-violating recommendations | Rules written as a checklist mapped to requirements.md's guardrail section | `docs/guardrails.md` listing each rule with its requirements.md reference | Done — `docs/guardrails.md` |
| 20 | Implement guardrail checks verified against live tool output and the policy corpus | Every figure and every customer-facing draft passes through the guardrail check before reaching the user | Log entry showing an output being labeled/filtered by the guardrail layer | Not started |
| 21 | Test guardrails against the "free gift for a 5-star review" request and a review-reply draft | Policy violation is correctly refused with an explanation and alternative; review reply is correctly labeled as a draft awaiting approval | Transcripts of both test runs | Not started |
| 22 | Implement caching for RAG embeddings and frequent analytics queries | Repeated identical queries hit the cache instead of re-querying | Log showing a cache miss then a cache hit on the repeat | Not started |
| 23 | Measure cache hit rate and latency improvement | Latency compared for cached vs. uncached calls with documented improvement | Before/after latency numbers committed to the repo | Not started |
| 24 | Run all 6 sample queries from requirements.md end-to-end; fix bugs | All 6 run and are compared against the expected-answers table | Filled-in expected-answers table with actual output and pass/fail per row | Not started |
| 25 | Surface guardrail status, draft-approval state, and cache hit/miss as visible badges in the Gradio UI | UI visibly shows guardrail blocks, draft-pending labels, and cache hits | Screenshots showing all three badge states | Not started |

## Week 4: Observability, Evals & Demo Readiness (9 tasks)
**Demo Goal:** Full live walkthrough: Gradio UI + observability dashboard, an eval score shown before/after your error-analysis fixes, and a policy-violation refusal on demand.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion | Status |
|---|---|---|---|---|
| 26 | Instrument observability: log retrievals, tool calls, guardrail triggers, and tool failures | Every event for one request shares a single trace ID | Exported trace for one request showing all event types tied together | Not started |
| 27 | Build an eval harness from the expected-answers table with pass/fail scoring | Each of the 6 rows is an automated test case with a scorer | Eval script committed, runnable with one command | Done (pulled forward) — `uv run python -m seller_pulse.evals.agent_eval`; 15 scored + 3 known-gap cases from `queries.jsonl` (not the 6 rows), 4 scored dimensions; see `docs/evals.md` |
| 28 | Run the eval suite against the synthetic seller data; record baseline scores | Suite runs successfully and produces a baseline score | Saved baseline report (score, timestamp, per-case pass/fail) | Pulled forward — baseline 12/15 (80%), 2026-10-13, in `docs/evals.md`; committed clean report pending a re-run at HEAD |
| 29 | Do error analysis: categorize failures, find root causes, pick top 3 fixes | Every failing case is categorized (retrieval miss, tool error, guardrail miss, fabricated figure, latency) with a root cause and prioritized fix | Error-analysis table committed | Not started |
| 30 | Apply the top fixes and re-run the eval suite; record the improvement | Score improves measurably over baseline after the fixes | Before/after eval report showing the score delta | Not started |
| 31 | Build a dashboard: tool-call failure rate, draft-approval turnaround, guardrail trigger count | Dashboard shows real data and is reachable from the UI | Screenshot/link of the live dashboard with real run data | Not started |
| 32 | Handle edge cases: analytics API timeout, ambiguous listing references, no catalog/review match | Each edge case produces a graceful fallback instead of a crash | Log/transcript of each edge case being triggered and handled | Not started |
| 33 | Prepare the demo script: Meera persona, 2-3 live queries, a memory demo, the scorecard | Script covers all elements and is timed to the demo slot | Script document + timed rehearsal note | Not started |
| 34 | Final rehearsal, deploy the demo build, record a backup demo video | Live demo runs end-to-end without failure; build deployed and reachable; backup video exists | Deployment link + backup video link, both in README | Not started |

## Stretch Goals (optional; the core path above is the safe, required build)
- Baseline comparison: run the same requests through a vanilla LLM with no RAG/tools/guardrails, and show side-by-side why grounded, policy-aware seller support matters.
- Red-team your own agent: try to get it to auto-publish a review reply or recommend a policy-violating tactic anyway (misleading phrasing, indirect requests), then harden the guardrail against what worked.
- Add a proactive "morning brief" that summarizes overnight orders, low stock, and new reviews without being asked.
- Set and hit a latency/cost budget (e.g., under 3s and under $0.01/query) and show the before/after numbers.
- (Add your own ideas here as the team comes up with them.)
