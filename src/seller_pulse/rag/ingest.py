"""Ingestion pipeline: policy corpus and seller reviews into Chroma.

Idempotent via `upsert` on stable ids (`pol-2a`, `REV-528`): re-running replaces rows in
place rather than duplicating them. There is no delete-and-rebuild.

Listings are read here — to resolve a review's title and to validate seller ownership — but
never embedded. `main()`'s console output states that plainly; it's the single most common
thing to misread about this design (see `plan/rag-08-ingest.md`).
"""

import csv
from pathlib import Path

from chromadb.api import ClientAPI

from seller_pulse.config import (
    DEFAULT_CHROMA_PATH,
    DEFAULT_LISTINGS_PATH,
    DEFAULT_POLICY_PATH,
    DEFAULT_REVIEWS_PATH,
    load_settings,
)
from seller_pulse.inventory import get_listing
from seller_pulse.rag.policy import load_chunks
from seller_pulse.rag.store import get_client, policy_collection, review_collection


def ingest_policy(client: ClientAPI, policy_path: Path = DEFAULT_POLICY_PATH) -> int:
    chunks = load_chunks(policy_path)
    policy_collection(client).upsert(
        ids=[chunk.chunk_id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=[chunk.metadata for chunk in chunks],
    )
    return len(chunks)


def ingest_reviews(client: ClientAPI, *, reviews_path: Path = DEFAULT_REVIEWS_PATH) -> int:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str | int]] = []

    with open(reviews_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sku = row["sku"]
            listing = get_listing(sku)

            if listing is not None and listing.seller_id != row["seller_id"]:
                raise ValueError(
                    f"review {row['review_id']} has seller_id {row['seller_id']!r} but "
                    f"listing {sku} belongs to seller_id {listing.seller_id!r}: the review "
                    "would be invisible to the listing's owner"
                )

            # A SKU absent from the catalog is a data error, but one to survive with a
            # degraded document rather than fail the whole ingest — 65 of 150 SKUs have no
            # reviews, so the reverse (a review with no listing) is the surprising case.
            title = listing.title if listing is not None else sku

            ids.append(row["review_id"])
            documents.append(f"{title}. {row['comment']}")
            metadatas.append(
                {
                    "seller_id": row["seller_id"],
                    "sku": sku,
                    "rating": int(row["rating"]),
                    "date": row["date"],
                    "title": title,
                }
            )

    review_collection(client).upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(ids)


def main() -> None:
    client = get_client()

    policy_count = ingest_policy(client)
    review_count = ingest_reviews(client)

    with open(DEFAULT_LISTINGS_PATH, newline="", encoding="utf-8") as f:
        catalog_count = sum(1 for _ in csv.DictReader(f))

    seller_id = load_settings().seller_id

    print(f"policy_kb      : {policy_count} chunks (global, no tenant key)")
    print(f"seller_reviews : {review_count} chunks (seller_id={seller_id})")
    print(f"catalog        : {catalog_count} listings (structured, not embedded)")
    print()
    print(f"vector store at {DEFAULT_CHROMA_PATH}")


if __name__ == "__main__":
    main()
