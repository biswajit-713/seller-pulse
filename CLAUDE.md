# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SellerPulse: a seller-engagement assistant for a solo marketplace seller (persona: Meera
Iyer, ~150-SKU home-decor store). Full spec: `docs/requirements.md`; narrative rationale:
`docs/6-pager.md`; the build is sequenced as a 4-week task plan in `docs/tasks.md` — check
it to see what stage a given piece of code belongs to (Week 1: RAG + UI only; Week 2: tools
+ MCP + memory; Week 3: guardrails + caching; Week 4: observability + evals).

Currently implemented: the Gradio chat UI; RAG ingestion + retrieval (`rag/`), whose
context is injected into the system prompt; a tool-calling loop (`agent.py`) over two
analytics tools (`get_sales_analytics`, `check_inventory_status`), which the app loads from its
own stdio MCP server (`mcp_server.py`, via `mcp_tools.py`), calling a real model through
LangChain's `ChatGroq`; prompt routing (`router.py`: a classifier picks the system-prompt
modules and tools per turn; `ROUTING=off` disables it); seller-preference memory
(`memory.py`: in-process `save_preference` / `list_preferences` tools, saved preferences
recalled into every turn's prompt); and an "Agent trace" panel under the chat
(`trace_view.py`: routes, tool calls, preferences applied, guardrail result); and a
post-generation guardrail output check (`guardrails.py`: unsourced figures/ids and publish
claims annotated, not blocked; draft-pending and policy-refusal status recorded; see
`docs/guardrails.md`). Week 2 is closed out (`plan/w2-17`); Week 3 guardrails (#19–#21) are
done (`plan/week-3/gr-07`), caching is not started. The build sequence lives in `plan/` (`STATUS.md` +
per-task files).
`plan/` is gitignored, so it never shows up in `git diff` or in a
commit — don't assume its absence from `git status` means it's untracked-and-safe-to-ignore.

## Workflow

Never run `git commit` (or `git push`) on your own initiative. Make the requested changes
and leave them staged/unstaged for the user to review and commit themselves.

If documentation (`docs/`, `plan/`, READMEs, this file) conflicts with the code, the code
supersedes — treat the code as the source of truth and flag the stale doc to the user.

## Commands

```bash
uv sync                          # install/update deps into .venv
cp .env.example .env             # first-time setup; set GROQ_API_KEY (LLM_PROVIDER=groq) and SELLER_ID (required); ROUTER_MODEL optional (blank → DEFAULT_ROUTER_MODEL), ROUTING=on|off (default on), MEMORY_PATH optional (blank → data/memory)
uv run python -m seller_pulse    # run the app — Gradio chat at http://localhost:7860
uv run pytest                    # run tests (dev group: pytest, pytest-asyncio; asyncio_mode=auto)
uv run python -m seller_pulse.mcp_server  # analytics MCP server on stdio, standalone (the app spawns its own)
uv run python -m seller_pulse.evals.retrieval_eval  # offline retrieval regression check, expect 10/10
uv run python -m seller_pulse.evals.agent_eval [--case AE-NN]  # live end-to-end eval, see docs/evals.md; full run eats Groq daily quota
```

No lint or format tooling is configured yet (no ruff in `pyproject.toml`) — don't assume
`uv run ruff` or similar exists. Tests live in `tests/` and must not hit the network or need
an API key — anything that would call Groq uses a fake.

## Architecture

Request pipeline, sequenced in `chat.py:respond`: `sanitize.py` → `chat.py:to_messages`
(Gradio history → `{role, content}` messages) → `router.py:classify_query` (multi-label
`data`/`reviews`/`policy`/`memory` on a separate small router model, strict JSON-schema
output, 4s timeout, fails open to all routes) run concurrently with `rag/retrieval.py` →
`prompts.py:build_system_prompt(routes)` (`CORE` always, plus one module per routed
`data`/`reviews`/`policy`, in fixed order; `memory` has no module) + `rag/context.py` +
`prompts.py:render_preferences` (saved preferences, every turn, whatever the routes) →
`agent.py:run_agent` (async model → tool calls → results loop) with only the routed tools
(`router.py:tools_for` over `ROUTE_TOOLS`: `data` → the two analytics tools, `memory` → the
two preference tools; `reviews`/`policy` bind none) → `guardrails.py:check_output` (no model
call; checks the final answer against this turn's tool calls, the rendered context block, the
seller's message and saved preferences) → `guardrails.py:annotate` (appends caution lines).
The number/id tokeniser lives in `guardrails.py`; `evals/checks.py:check_groundedness` reuses
it. Analytics tools wrap `sales.py` and
`inventory.py` twice, sharing names and descriptions: `tools.py` (in-process; tests and the
agent eval) and `mcp_server.py` (stdio; the app loads it through
`mcp_tools.py:load_mcp_tools`, a fresh server subprocess per call, results parsed back into
the envelope dict). Memory tools (`tools.py:build_memory_tools`) stay in-process over
`memory.py:PreferenceStore` — one JSON file per seller under `MEMORY_PATH`, re-read every
turn, three keys (`notification_cadence`, `reply_tone`, `restock_threshold`); see
`docs/memory.md`. `respond` returns a `ChatResult` (text, tool-call trace, routes, fallback
flag, preferences applied, `guardrail` report); `app.py` (a `gr.Blocks` wrapping `ChatInterface`) shows the text
and renders the rest with `trace_view.py:render_trace` into the "Agent trace" accordion. The
`/chat` API therefore returns `(text, trace_markdown)`. The LLM seam is `llm/base.py:LLMClient`, a `Protocol` exposing one
property, `chat_model` (a LangChain `BaseChatModel`, for `bind_tools`); `agent.py` owns the
`Message` → LangChain translation. `llm/groq_client.py` builds `ChatGroq` lazily.
`llm/factory.py:get_client` builds `GroqLLMClient` from `Settings.llm_provider`/
`groq_api_key`/`groq_model` — `groq` is the only supported provider now;
`get_router_client` builds the classifier's model (`ROUTER_MODEL`, temperature 0).

### Data

`data/listings.csv`, `data/reviews.csv`, `data/sales.csv` are the synthetic dataset. All
three carry `seller_id` as their first column (currently one constant value,
`SELLER-001`) — it's the tenant partition key a future `seller_reviews` / `policy_kb`
collection split relies on, not dead data.

`data/policy/seller_policy_handbook.md` is the marketplace policy corpus used by the
guardrail/RAG layers; the source doc is `docs/seller_policy_handbook.pdf`.

Two listings (SKU-1013, SKU-1020) are intentionally inconsistent — `stock_qty` 0 but
`status: Active` — seeding the "still-active listing after stock ran out" case that a
policy rule and specific reviews depend on. Do not "fix" this data without reading
`plan/rag-03-seller-id-column.md` first; it's a deliberate test
fixture.
