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

Set `GROQ_API_KEY` in `.env` — `LLM_PROVIDER` defaults to `groq`.

The first ingest downloads the embedding model (~80 MB compressed, ~167 MB
unpacked) to `~/.cache/chroma` and takes 30-60s; later runs take seconds.

## Run

```bash
uv run python -m seller_pulse
```

Opens a chat at http://localhost:7860. Type a natural-language question; the
message is sanitized, bundled with the system prompt and the conversation so far,
and sent to Groq (via LangChain's `ChatGroq`).

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
