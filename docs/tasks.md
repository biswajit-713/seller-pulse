# SellerPulse: 4-Week Task Plan
*Core path: 34 one-hour tasks; this is the safe, required build every team should be able to finish. Stretch Goals (bottom) are optional add-ons for teams with extra time.*

## Week 1: Foundations, RAG & UI (11 tasks)
**Demo Goal:** A live Gradio chat UI that answers a seller's performance question with a RAG-grounded diagnosis of a specific listing; no tools, memory, or guardrails yet, but it's clickable and shareable. Plus two written deliverables: an Amazon-style 6-pager and a PR/FAQ.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion |
|---|---|---|---|
| 1 | Kickoff: assign roles, review requirements.md and Meera Iyer's persona/objective, agree on tech stack | Roles assigned (prompt/RAG, tools/MCP, memory, guardrails/caching, observability/UI owners); requirements.md read by everyone; stack agreed | A `docs/team.md` listing roles and stack, with each member confirming they've read requirements.md |
| 2 | Write an Amazon-style 6-pager for SellerPulse: narrative memo covering the problem, the customer (Meera), the solution, goals & non-goals, key risks/mitigations, and success metrics | 6-pager committed as a narrative document (no slides/bullets-only sections); every section from the standard format is present and specific to SellerPulse, not generic | `docs/6-pager.md` in repo, reviewed and agreed on by the whole team |
| 3 | Write a PR/FAQ for SellerPulse: a mock press release announcing the launch, plus an FAQ covering customer questions and internal/guardrail questions | PR/FAQ committed; press release is written from the customer's (Meera's) point of view; FAQ has at least 5 questions, including at least one on data handling and one on guardrails/policy compliance | `docs/pr-faq.md` in repo, reviewed and agreed on by the whole team |
| 4 | Set up the git repository: initialize repo, agree on branch strategy, add .gitignore, write a README | Repo exists remotely with main + feature branches; README lets a fresh clone run the project | A teammate clones the repo and runs it successfully from README alone |
| 5 | Draft the system prompt: seller-engagement tone, "never invent a number" rule, draft-only output rule | Prompt file committed; 2 manual test prompts confirm figures are only ever tool-sourced and outputs are labeled as drafts | Prompt file in repo + pasted transcript of the 2 test runs |
| 6 | Generate a synthetic dataset of a seller's listings, sales history, inventory levels, orders, and reviews | Dataset file committed covering ~150 SKUs with several weeks of sales/order history | Dataset file in repo + a summary count of listings/orders/reviews |
| 7 | Prepare the RAG corpus: listing content, past reviews, and marketplace seller-policy documents | Corpus covers all 6 sample queries in requirements.md, especially the underperforming-listing diagnosis and the policy-violation case | Corpus files committed with item/document count |
| 8 | Build the ingestion pipeline: chunk and embed the corpus into a vector store | Pipeline runs with no errors; vector store has the expected chunk count | Console log showing chunk/embedding count |
| 9 | Implement retrieval and test against "why is my Boho Wall Hanging listing underperforming?" | Relevant listing/review chunk(s) appear in the top-3 retrieved results | Logged query + retrieved chunks with a correct/incorrect judgment |
| 10 | Wire a minimal prototype: seller question → grounded diagnosis (no tools yet) | Full query→diagnosis round trip runs without crashing and reflects the corpus data | Terminal/notebook transcript of one successful run |
| 11 | Build a Gradio chat UI for the prototype and deploy it locally with a shareable link | Gradio app launches and returns a grounded diagnosis for a real query | Screenshot of the running UI + shareable link posted to the team channel |

## Week 2: Tools, MCP & Memory (7 tasks)
**Demo Goal:** The same Gradio UI now pulls live sales/inventory figures and drafts a review reply, and remembers the seller's notification preferences across two visits; visible live in the chat.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion |
|---|---|---|---|
| 12 | Design tool specs: `get_sales_analytics(seller_id, period)` and `check_inventory_status(sku)` | Written spec for both tools: inputs, outputs, error cases | `docs/tools.md` with both signatures and example input/output |
| 13 | Implement the sales-analytics tool | Returns correct revenue/units/orders for a known period and a clear error for an invalid one | Test log showing both cases |
| 14 | Implement the inventory-status tool | Returns correct stock level for a known SKU and a clear error for an unknown one | Test log showing both cases |
| 15 | Set up MCP to expose both tools to the agent; test a full round trip | Agent calls both tools via MCP and uses their results in a live response | Trace/log of one query showing the response built from tool output |
| 16 | Design the memory schema: notification cadence, reply tone, and restock threshold preferences | Schema documented; a record can be written and read back correctly | Schema doc + log of one record written and retrieved |
| 17 | Integrate memory; test preference recall (e.g., "notify me every Friday about low best-sellers") across 2 sessions | Preference stated in session 1 is correctly recalled, unprompted, in session 2 | Transcripts of both sessions showing the preference and its recall |
| 18 | Wire tools and memory into the Gradio UI via an expandable "agent trace" panel | Panel lists each tool call and the recalled preferences for the response | Screenshot of the panel expanded on a real query |

## Week 3: Guardrails & Caching (7 tasks)
**Demo Goal:** In the live UI, show the agent refuse a review-manipulation request and label a review-reply draft as pending approval, and show a visible speed-up (cache hit badge) on a repeated analytics query.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion |
|---|---|---|---|
| 19 | Codify guardrail rules: no fabricated figures, no auto-publishing, no policy-violating recommendations | Rules written as a checklist mapped to requirements.md's guardrail section | `docs/guardrails.md` listing each rule with its requirements.md reference |
| 20 | Implement guardrail checks verified against live tool output and the policy corpus | Every figure and every customer-facing draft passes through the guardrail check before reaching the user | Log entry showing an output being labeled/filtered by the guardrail layer |
| 21 | Test guardrails against the "free gift for a 5-star review" request and a review-reply draft | Policy violation is correctly refused with an explanation and alternative; review reply is correctly labeled as a draft awaiting approval | Transcripts of both test runs |
| 22 | Implement caching for RAG embeddings and frequent analytics queries | Repeated identical queries hit the cache instead of re-querying | Log showing a cache miss then a cache hit on the repeat |
| 23 | Measure cache hit rate and latency improvement | Latency compared for cached vs. uncached calls with documented improvement | Before/after latency numbers committed to the repo |
| 24 | Run all 6 sample queries from requirements.md end-to-end; fix bugs | All 6 run and are compared against the expected-answers table | Filled-in expected-answers table with actual output and pass/fail per row |
| 25 | Surface guardrail status, draft-approval state, and cache hit/miss as visible badges in the Gradio UI | UI visibly shows guardrail blocks, draft-pending labels, and cache hits | Screenshots showing all three badge states |

## Week 4: Observability, Evals & Demo Readiness (9 tasks)
**Demo Goal:** Full live walkthrough: Gradio UI + observability dashboard, an eval score shown before/after your error-analysis fixes, and a policy-violation refusal on demand.

| # | Task (~1 hr) | Definition of Done | Evidence of Completion |
|---|---|---|---|
| 26 | Instrument observability: log retrievals, tool calls, guardrail triggers, and tool failures | Every event for one request shares a single trace ID | Exported trace for one request showing all event types tied together |
| 27 | Build an eval harness from the expected-answers table with pass/fail scoring | Each of the 6 rows is an automated test case with a scorer | Eval script committed, runnable with one command |
| 28 | Run the eval suite against the synthetic seller data; record baseline scores | Suite runs successfully and produces a baseline score | Saved baseline report (score, timestamp, per-case pass/fail) |
| 29 | Do error analysis: categorize failures, find root causes, pick top 3 fixes | Every failing case is categorized (retrieval miss, tool error, guardrail miss, fabricated figure, latency) with a root cause and prioritized fix | Error-analysis table committed |
| 30 | Apply the top fixes and re-run the eval suite; record the improvement | Score improves measurably over baseline after the fixes | Before/after eval report showing the score delta |
| 31 | Build a dashboard: tool-call failure rate, draft-approval turnaround, guardrail trigger count | Dashboard shows real data and is reachable from the UI | Screenshot/link of the live dashboard with real run data |
| 32 | Handle edge cases: analytics API timeout, ambiguous listing references, no catalog/review match | Each edge case produces a graceful fallback instead of a crash | Log/transcript of each edge case being triggered and handled |
| 33 | Prepare the demo script: Meera persona, 2-3 live queries, a memory demo, the scorecard | Script covers all elements and is timed to the demo slot | Script document + timed rehearsal note |
| 34 | Final rehearsal, deploy the demo build, record a backup demo video | Live demo runs end-to-end without failure; build deployed and reachable; backup video exists | Deployment link + backup video link, both in README |

## Stretch Goals (optional; the core path above is the safe, required build)
- Baseline comparison: run the same requests through a vanilla LLM with no RAG/tools/guardrails, and show side-by-side why grounded, policy-aware seller support matters.
- Red-team your own agent: try to get it to auto-publish a review reply or recommend a policy-violating tactic anyway (misleading phrasing, indirect requests), then harden the guardrail against what worked.
- Add a proactive "morning brief" that summarizes overnight orders, low stock, and new reviews without being asked.
- Set and hit a latency/cost budget (e.g., under 3s and under $0.01/query) and show the before/after numbers.
- (Add your own ideas here as the team comes up with them.)
