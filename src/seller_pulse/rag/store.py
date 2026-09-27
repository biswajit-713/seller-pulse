"""Chroma client and collection accessors.

Two collections, not one collection plus a `doc_type` filter — see `plan/rag-07-store.md` for
why tenancy, write pattern, and scale all point the same way:

- `policy_kb` — global marketplace policy, one copy for every seller, curated quarterly.
- `seller_reviews` — per-seller buyer reviews, append-only, every row carrying `seller_id`.

Embedding function is pinned explicitly below — `DefaultEmbeddingFunction`, Chroma's bundled
ONNX build of `all-MiniLM-L6-v2` (384 dims, no `sentence_transformers` install required) —
rather than left as whatever the installed Chroma version happens to default to. That turns an
inherited default into a decision. It's baked into each collection's metadata at creation
time: changing `_embedding_function` means deleting `data/chroma/` and re-ingesting, since
Chroma 1.x refuses a query against a mismatched embedding config.
"""

from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from seller_pulse.config import DEFAULT_CHROMA_PATH

POLICY_COLLECTION = "policy_kb"
REVIEW_COLLECTION = "seller_reviews"

_embedding_function = DefaultEmbeddingFunction()


def get_client(db_path: Path = DEFAULT_CHROMA_PATH) -> ClientAPI:
    return chromadb.PersistentClient(
        path=str(db_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def policy_collection(client: ClientAPI) -> Collection:
    return client.get_or_create_collection(
        name=POLICY_COLLECTION,
        metadata={"hnsw:space": "cosine"},
        embedding_function=_embedding_function,
    )


def review_collection(client: ClientAPI) -> Collection:
    return client.get_or_create_collection(
        name=REVIEW_COLLECTION,
        metadata={"hnsw:space": "cosine"},
        embedding_function=_embedding_function,
    )
