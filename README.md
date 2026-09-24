# seller-pulse

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
cp .env.example .env  # then fill in ANTHROPIC_API_KEY
```

## Run

```bash
uv run python -m seller_pulse
```

## Stack

- **gradio** — UI
- **anthropic** — Claude API client
- **chromadb** — vector store
- **python-dotenv** — loads secrets from `.env`
- CSV reading via the standard library `csv` module
