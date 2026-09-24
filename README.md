# seller-pulse

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) (optional — see [Without uv](#without-uv))

## Setup

```bash
uv sync
cp .env.example .env
```

No API key is needed yet — `LLM_PROVIDER` defaults to `fake`, which returns a
stubbed reply without calling a model.

## Run

```bash
uv run python -m seller_pulse
```

Opens a chat at http://localhost:7860. Type a natural-language question; the
message is sanitized, bundled with the system prompt and the conversation so far
into an Anthropic-shaped request, and sent to the configured client.

Set `LLM_PROVIDER=anthropic` to select the real client — it is a placeholder and
currently raises `NotImplementedError`.

## Without uv

Plain venv + pip works too:

```bash
python3.12 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install .
cp .env.example .env
python -m seller_pulse
```

`pip install .` fetches the `uv-build` backend from PyPI, so uv itself is not
needed on PATH. Note that pip ignores `uv.lock`, so dependencies resolve fresh
rather than to the pinned versions.

## Stack

- **gradio** — UI
- **anthropic** — Claude API client
- **chromadb** — vector store
- **python-dotenv** — loads secrets from `.env`
- CSV reading via the standard library `csv` module
