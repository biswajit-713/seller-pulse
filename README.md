# seller-pulse

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

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

## Stack

- **gradio** — UI
- **anthropic** — Claude API client
- **chromadb** — vector store
- **python-dotenv** — loads secrets from `.env`
- CSV reading via the standard library `csv` module
