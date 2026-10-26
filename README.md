# seller-pulse

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) (optional — see [Without uv](#without-uv))

## Setup

```bash
uv sync
cp .env.example .env
uv run python -m seller_pulse.rag.ingest
```

Set `GROQ_API_KEY` and `SELLER_ID` in `.env` — `LLM_PROVIDER` defaults to `groq`. `SELLER_ID`
is required (the dataset uses `SELLER-001`); every tool is bound to it.

The first ingest downloads the embedding model (~80 MB compressed, ~167 MB
unpacked) to `~/.cache/chroma` and takes 30-60s; later runs take seconds.

## Run

```bash
uv run python -m seller_pulse
```

Opens a chat at http://localhost:7860. Type a natural-language question; the
message is sanitized, bundled with the system prompt and the conversation so far,
and sent to Groq (via LangChain's `ChatGroq`). The model can call tools:

- **Sales and inventory** (`get_sales_analytics`, `check_inventory_status`) are served by an MCP
  server, `seller_pulse.mcp_server`. The app starts it itself over stdio, one subprocess per
  tool call (~1 s each), so there is nothing extra to run. To start it on its own (for an MCP
  client), run `uv run python -m seller_pulse.mcp_server`.
- **Preferences** (`save_preference`, `list_preferences`) are stored in
  `data/memory/<SELLER_ID>.json` (override with `MEMORY_PATH`). Saved preferences are read
  into every turn, so they still apply after a restart. See [`docs/memory.md`](docs/memory.md).

Query embeddings and sales/inventory tool results are cached in-process (`cache.py`). Set
`CACHING=off` to disable; `CACHE_EMBED_MAX`, `CACHE_TOOL_MAX`, `CACHE_TOOL_TTL_S` tune sizes and
TTL (see `.env.example`). Cached tool calls show "(cached)" in the trace. See
[`docs/caching.md`](docs/caching.md).

Open the **Agent trace** panel under the chat to see the routes, the tool calls, and the
preferences applied for the last reply.

## Tests

```bash
uv run pytest
```

Offline: no network or `GROQ_API_KEY` needed.

## Without uv

Plain venv + pip works too:

```bash
python3.12 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
python -m seller_pulse
```

`pip install -e .` fetches the `uv-build` backend from PyPI, so uv itself is
not needed on PATH. Note that pip ignores `uv.lock`, so dependencies resolve
fresh rather than to the pinned versions.

## Stack

- **gradio** — UI
- **langchain-groq** — Groq API client
- **chromadb** — vector store
- **mcp**, **langchain-mcp-adapters** — the analytics tools' MCP server and the app's client
- **python-dotenv** — loads secrets from `.env`
- CSV reading via the standard library `csv` module

## Retrieval Statistics (in progress — cases grow over the coming weeks)

```bash
uv run python -m seller_pulse.evals.retrieval_eval
```

Scores the vector store against 10 cases in `data/synthetic_queries/retrieval_cases.jsonl` and
prints each case's query, the full top-k retrieved ids with distances, and a pass/fail verdict —
the log is the deliverable, there is no quiet mode. Expected last line: `RESULT: PASS`
(`10/10 cases      target >= 9/10`). Run it after ingesting, and any time the corpus, chunking,
or embedding config changes, to catch a retrieval regression before it reaches the chat UI.

No LLM call, no network beyond the local Chroma store, and no `GROQ_API_KEY` needed — it embeds
queries with the same store-bound embedding function `rag/ingest.py` used, so the score reflects
the vector store itself, not a model's phrasing of the answer.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Scored pass rate ≥ 9/10. |
| `1` | Below threshold — the retrieval metric regressed. |
| `2` | Could not run at all — `data/chroma/` is missing or empty (run the ingest command first), or a case references an id that doesn't exist in the store. |

Pass `--json` to emit one JSON object per case instead of the human-readable log, for scripting
or a baseline report. See [`docs/retrieval.md`](docs/retrieval.md) for the measured scores and
what the five Tier 1 queries this checks actually cover, and
[`docs/verification.md`](docs/verification.md) for the manual verification pass this feeds into.

## Route eval

```bash
uv run python -m seller_pulse.evals.route_eval [--model X] [--runs N] [--pace S] [--json] [--no-report]
```

Each turn, a small classifier (`router.classify_query`, model `ROUTER_MODEL`) picks which system
prompt modules (`data` / `reviews` / `policy`) and tools to load; `memory` loads only the
preference tools. This eval scores that
classifier against the gold route sets in `data/synthetic_queries/route_cases.jsonl`. It makes
live Groq calls and needs `GROQ_API_KEY`. Calls are spaced out (`--pace`) to stay under Groq's
per-minute token limit. Run it whenever the classifier prompt, its few-shot examples, or
`ROUTER_MODEL` change.

**The gate** must hold on every run:
- **`policy` recall is 100%.** Missing `policy` on a request that breaks a rule is the
  expensive mistake.
- **`data` recall is at least 95%.**
- **`memory` recall is 100%.** A miss means a preference the seller stated is never saved.
- **No fallbacks.** On an error or timeout the classifier routes to everything, which would
  hide a classifier problem.

Exit codes: `0` gate met, `1` gate missed, `2` could not run.

To run the app or the agent eval without the classifier (all modules, every tool), set
`ROUTING=off` in `.env`.

## Agent eval

```bash
uv run python -m seller_pulse.evals.agent_eval [--case AE-NN ...] [--delay S] [--json] [--no-report]
```

Runs 20 synthetic queries end to end (router → retrieval → agent → tools) and scores each on
four dimensions: `tool_use`, `accuracy`, `grounded`, `behavior`. Scoring mixes deterministic
checks with an LLM judge. Live Groq calls; needs `GROQ_API_KEY` and an ingested store. Pass
threshold is 80% of the 16 scored cases. Exit codes: `0` met, `1` below, `2` could not run.
A full run uses much of the agent model's daily Groq token budget, so use `--case` while
iterating. See [`docs/evals.md`](docs/evals.md) for the scoring rules and the baseline.

## Cache measurement

```bash
uv run python -m seller_pulse.evals.cache_live [--pace S] [--json PATH]
```

Asks a fixed set of questions twice each and reports cold vs warm tool latency and hit rates.
Live Groq calls; needs `GROQ_API_KEY` and an ingested store. Results in
[`docs/caching.md`](docs/caching.md).
