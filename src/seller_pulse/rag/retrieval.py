"""Data access over the two Chroma collections: `Hit` and the two stores.

`ReviewStore` binds `seller_id` at construction so that unscoped access is unreachable, not
merely discouraged — no method takes a `seller_id` argument, so no call site can issue a query
that crosses tenants. `PolicyStore` has no seller scope, deliberately: `policy_kb` is global,
one copy for every seller (see `rag/store.py`), so adding a scope there would be cargo-culting
the review store's shape onto data that has no tenancy.

`Hit.distance` is `None` for an exact metadata fetch (`Collection.get()`, no query vector) and
a float for a semantic search (`Collection.query()`). Writing `0.0` for the former would read
as "perfect semantic match" to every downstream consumer, including the harness — the
`Optional` is the honest type.

Review ids come from Chroma's `ids`, not from metadata — `rag/ingest.py` writes
`{seller_id, sku, rating, date, title}`, no `review_id` key. Policy chunks additionally carry
`chunk_id` in metadata (`rag/policy.py`), but `Hit.id` is populated from `ids` in both cases.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chromadb.api import ClientAPI

from seller_pulse.rag.store import policy_collection, review_collection

POLICY_K = 2
REVIEW_K = 6
LOW_RATING = 2


@dataclass(frozen=True)
class Hit:
    id: str
    text: str
    distance: float | None
    metadata: Mapping[str, Any]
    citation: str


def _review_citation(hit_id: str, metadata: Mapping[str, Any]) -> str:
    return f"{hit_id} · {metadata['sku']} · {metadata['rating']}★ · {metadata['date']}"


def _policy_citation(hit_id: str, metadata: Mapping[str, Any]) -> str:
    return f"{hit_id} · {metadata['doc_title']} > {metadata['section_title']}"


def _query_hits(result: Mapping[str, Any], *, citation_fn) -> list[Hit]:
    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    return [
        Hit(
            id=hit_id,
            text=document,
            distance=distance,
            metadata=metadata,
            citation=citation_fn(hit_id, metadata),
        )
        for hit_id, document, metadata, distance in zip(ids, documents, metadatas, distances)
    ]


def _get_hits(result: Mapping[str, Any], *, citation_fn) -> list[Hit]:
    ids = result["ids"]
    documents = result["documents"]
    metadatas = result["metadatas"]
    return [
        Hit(
            id=hit_id,
            text=document,
            distance=None,
            metadata=metadata,
            citation=citation_fn(hit_id, metadata),
        )
        for hit_id, document, metadata in zip(ids, documents, metadatas)
    ]


class ReviewStore:
    def __init__(self, client: ClientAPI, *, seller_id: str) -> None:
        self._collection = review_collection(client)
        self._seller_id = seller_id

        total = self._collection.count()
        if total == 0:
            raise RuntimeError(
                "seller_reviews is empty. Run: uv run python -m seller_pulse.rag.ingest"
            )
        if not self._collection.get(where={"seller_id": seller_id}, limit=1)["ids"]:
            raise RuntimeError(
                f"No reviews carry seller_id={seller_id!r} ({total} rows in the collection)."
            )

    def _where(self, extra: dict | None = None) -> dict:
        base = {"seller_id": self._seller_id}
        return base if extra is None else {"$and": [base, extra]}

    def search(self, query: str, *, k: int = REVIEW_K) -> list[Hit]:
        result = self._collection.query(
            query_texts=[query],
            n_results=k,
            where=self._where(),
        )
        return _query_hits(result, citation_fn=_review_citation)

    def low_rated(self, *, max_rating: int = LOW_RATING) -> list[Hit]:
        result = self._collection.get(where=self._where({"rating": {"$lte": max_rating}}))
        hits = _get_hits(result, citation_fn=_review_citation)
        return sorted(hits, key=lambda hit: (hit.metadata["rating"], hit.metadata["date"], hit.id))

    def all_reviews(self) -> list[Hit]:
        result = self._collection.get(where=self._where())
        hits = _get_hits(result, citation_fn=_review_citation)
        return sorted(hits, key=lambda hit: (hit.metadata["sku"], hit.metadata["date"], hit.id))


class PolicyStore:
    def __init__(self, client: ClientAPI) -> None:
        self._collection = policy_collection(client)

    def search(self, query: str, *, k: int = POLICY_K) -> list[Hit]:
        result = self._collection.query(query_texts=[query], n_results=k)
        return _query_hits(result, citation_fn=_policy_citation)

    def get(self, chunk_ids: Sequence[str]) -> list[Hit]:
        result = self._collection.get(ids=list(chunk_ids))
        return _get_hits(result, citation_fn=_policy_citation)
