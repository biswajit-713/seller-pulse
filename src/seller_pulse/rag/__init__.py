"""RAG corpus loading, ingestion and retrieval — the public surface.

`evaluate` is deliberately not re-exported here: it is a command (`uv run python -m
seller_pulse.rag.evaluate`), not a library surface, and importing it into the package would pull
the eval-case path into every consumer's import graph.
"""

from seller_pulse.rag.context import render_context
from seller_pulse.rag.retrieval import (
    Hit,
    PolicyStore,
    RetrievalResult,
    Retriever,
    Route,
    ReviewStore,
    build_retriever,
)
from seller_pulse.rag.stats import ReviewStats, SkuStats, compute

__all__ = [
    "Hit",
    "PolicyStore",
    "RetrievalResult",
    "Retriever",
    "ReviewStats",
    "ReviewStore",
    "Route",
    "SkuStats",
    "build_retriever",
    "compute",
    "render_context",
]
