"""Chroma client and collection accessors.

Two collections, not one collection plus a `doc_type` filter — see `plan/rag-07-store.md` for
why tenancy, write pattern, and scale all point the same way:

- `policy_kb` — global marketplace policy, one copy for every seller, curated quarterly.
- `seller_reviews` — per-seller buyer reviews, append-only, every row carrying `seller_id`.

Embedding model is Chroma's default sentence-transformers function, `all-MiniLM-L6-v2`
(384 dims), pinned in each collection's metadata at creation time. Changing it means deleting
`data/chroma/` and re-ingesting — Chroma 1.x refuses a query against a mismatched embedding
config.
"""

from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from seller_pulse.config import DEFAULT_CHROMA_PATH

POLICY_COLLECTION = "policy_kb"
REVIEW_COLLECTION = "seller_reviews"


def get_client(db_path: Path = DEFAULT_CHROMA_PATH) -> ClientAPI:
    return chromadb.PersistentClient(
        path=str(db_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def policy_collection(client: ClientAPI) -> Collection:
    return client.get_or_create_collection(
        name=POLICY_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def review_collection(client: ClientAPI) -> Collection:
    return client.get_or_create_collection(
        name=REVIEW_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
