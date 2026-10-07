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

`Retriever.retrieve()` runs policy and review similarity search on *every* question,
unconditionally — only the statistics path is gated on `_STATS_HINTS`. A keyword router that
skipped policy search on "no policy vocabulary" questions would drop the policy chunk on exactly
the queries where a seller is unknowingly asking to break a rule: SQ-14 ("add trending keywords
to titles so they rank higher") and SQ-25 ("say it's handmade from organic fibres and ships next
day") are both policy questions with no policy vocabulary at all. Retrieving unconditionally
costs one HNSW probe over 6 policy chunks and one over 111 reviews (~80ms warm) — cheap next to
that failure mode. An irrelevant policy chunk reaching the prompt is handled by the prompt
(cite a section only if it bears on the question), not by a keyword list that is wrong in both
directions.

The stats path is gated because it is a cost-and-shape question, not a relevance one: `compute()`
renders all 111 reviews into a per-SKU table, which would dominate the context block for a
question that has nothing to do with aggregates. Missing the hint just falls back to a normal
review search — a reasonable answer, not a wrong one.

A star rating named in the question ("the buyer who left me a 1-star about shipping") becomes a
metadata filter on the review search. The rating lives only in metadata — the embedded document
is `"{title}. {comment}"` — so without the filter "1-star" matches nothing and 4★/5★ "arrived
fast" reviews outrank the review the seller means (SQ-18: REV-586 ranked 12th). A rating a change
verb points *to* ("bump it to 4 stars") is the seller's target, not the review's, and is
ignored; a bare "to" ("reply to 2-star reviews") is not enough. Several distinct ratings, or a filter that matches no review, fall back to the
unfiltered search.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from chromadb.api import ClientAPI

from seller_pulse.rag.store import get_client, policy_collection, review_collection, warm_embedder

if TYPE_CHECKING:
    from seller_pulse.config import Settings
    from seller_pulse.rag.stats import ReviewStats

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

    def search(self, query: str, *, k: int = REVIEW_K, rating: int | None = None) -> list[Hit]:
        result = self._collection.query(
            query_texts=[query],
            n_results=k,
            where=self._where(None if rating is None else {"rating": rating}),
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


_STATS_HINTS = frozenset(
    "complain complaining complaint complaints worst best most least common commonly "
    "themes theme overall average typically ranking".split()
)


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
# A rating is a target only after a change verb ("bump it up to 4 stars"), so "reply to
# 2-star reviews" still filters on 2★. Up to three words may sit between verb and "to".
_CHANGE_VERBS = r"(?:bump|chang|rais|mov|updat|upgrad|increas|edit|switch|turn|get|got)\w*"
_RATING_PATTERN = re.compile(
    rf"(?P<target>\b{_CHANGE_VERBS}\s+(?:\w+\s+){{0,3}}?(?:in)?to\s+(?:an?\s+)?)?"
    r"\b(?P<n>[1-5]|one|two|three|four|five)\s*-?\s*(?:stars?\b|★)"
)


def mentioned_rating(question: str) -> int | None:
    """The single review rating the question names, or None if it names zero or several."""
    ratings = {
        _NUMBER_WORDS.get(match["n"]) or int(match["n"])
        for match in _RATING_PATTERN.finditer(question.casefold())
        if not match["target"]
    }
    return ratings.pop() if len(ratings) == 1 else None


class Route(StrEnum):
    STATS = "stats"  # aggregate question -> add computed statistics
    GENERAL = "general"  # policy + review similarity only


def classify(question: str) -> Route:
    tokens = set(re.findall(r"[a-z']+", question.casefold()))
    if tokens & _STATS_HINTS:
        return Route.STATS
    return Route.GENERAL


@dataclass(frozen=True)
class RetrievalResult:
    route: Route
    question: str
    reviews: tuple[Hit, ...] = ()
    policy: tuple[Hit, ...] = ()
    stats: "ReviewStats | None" = None

    @property
    def is_empty(self) -> bool:
        return not self.reviews and not self.policy and self.stats is None


class Retriever:
    def __init__(self, *, reviews: ReviewStore, policy: PolicyStore) -> None:
        self._reviews = reviews
        self._policy = policy

    def retrieve(self, question: str) -> RetrievalResult:
        from seller_pulse.rag.stats import compute

        route = classify(question)
        rating = mentioned_rating(question)
        reviews = self._reviews.search(question, rating=rating) if rating is not None else []
        return RetrievalResult(
            route=route,
            question=question,
            reviews=tuple(reviews or self._reviews.search(question)),
            policy=tuple(self._policy.search(question)),
            stats=compute(self._reviews) if route is Route.STATS else None,
        )


def build_retriever(settings: "Settings") -> Retriever:
    client = get_client(settings.chroma_path)
    retriever = Retriever(
        reviews=ReviewStore(client, seller_id=settings.seller_id),
        policy=PolicyStore(client),
    )
    warm_embedder()
    return retriever
