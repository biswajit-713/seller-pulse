# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SellerPulse: a seller-engagement assistant for a solo marketplace seller (persona: Meera
Iyer, ~150-SKU home-decor store). Full spec: `docs/requirements.md`; narrative rationale:
`docs/6-pager.md`; the build is sequenced as a 4-week task plan in `docs/tasks.md` — check
it to see what stage a given piece of code belongs to (Week 1: RAG + UI only; Week 2: tools
+ MCP + memory; Week 3: guardrails + caching; Week 4: observability + evals).

Currently implemented: the Gradio chat UI and the sanitize → bundle-history → LLM-client
pipeline, calling a real model through LangChain's `ChatGroq`. Tools, memory, and
guardrails are not wired up yet; RAG ingestion exists (`rag/`) but retrieval is not wired
into `chat.py` either — the in-progress build sequence lives in `plan/` (the `rag-*` files
are the active thread). `plan/` is gitignored, so it never shows up in `git diff` or in a
commit — don't assume its absence from `git status` means it's untracked-and-safe-to-ignore.

## Workflow

Never run `git commit` (or `git push`) on your own initiative. Make the requested changes
and leave them staged/unstaged for the user to review and commit themselves.

## Commands

```bash
uv sync                          # install/update deps into .venv
cp .env.example .env             # first-time setup; set GROQ_API_KEY (LLM_PROVIDER=groq)
uv run python -m seller_pulse    # run the app — Gradio chat at http://localhost:7860
uv run pytest                    # run tests (dev group: pytest, pytest-asyncio; asyncio_mode=auto)
```

No lint or format tooling is configured yet (no ruff in `pyproject.toml`) — don't assume
`uv run ruff` or similar exists. Tests live in `tests/` and must not hit the network or need
an API key — anything that would call Groq uses a fake.

## Architecture

Request pipeline, sequenced in `chat.py:respond`: `sanitize.py` → `chat.py:to_messages`
(Gradio history → `{role, content}` messages) → `llm/base.py:LLMClient`. That last piece is
the seam: a `Protocol` with one method, `complete(*, system, messages)`; `llm/groq_client.py`
translates that shape into LangChain message objects and calls `ChatGroq`.
`llm/factory.py:get_client` builds `GroqLLMClient` from `Settings.llm_provider`/
`groq_api_key`/`groq_model` — `groq` is the only supported provider now.

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
