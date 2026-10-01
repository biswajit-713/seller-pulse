# SellerPulse: Team & Stack

## Roles

Both team members own all five areas jointly — no formal split by milestone owner.

| Area | Owner(s) |
|---|---|
| Prompt / RAG | Biswajit, Bharat Maripi |
| Tools / MCP | Biswajit, Bharat Maripi |
| Memory | Biswajit, Bharat Maripi |
| Guardrails / caching | Biswajit, Bharat Maripi |
| Observability / UI | Biswajit, Bharat Maripi |

## Tech stack

- **LLM:** LangChain + ChatGroq (`src/seller_pulse/llm/groq_client.py`)
- **UI:** Gradio (`src/seller_pulse/app.py`)
- **Vector store:** Chroma (`src/seller_pulse/rag/store.py`)

