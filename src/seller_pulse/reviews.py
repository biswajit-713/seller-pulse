"""The reviews domain: per-product review aggregation.

Reviews are also embedded for retrieval (`rag/`), but a question about *which products* have no
reviews, or a 1-star review, is a join and a group-by over the catalog — not a neighbourhood a
top-k search can return, and an unreviewed SKU has no review text to match at all. So this
aggregates `reviews.csv` against the listings, in Python, and hands the model the figures.

Review text stays with RAG: this returns counts and ratings, not comments.

Like `inventory.py`, the CSV is loaded once at import.
"""

import csv
from collections import defaultdict

from seller_pulse.config import DEFAULT_REVIEWS_PATH
from seller_pulse.inventory import listings_for

MAX_REVIEW_ITEMS = 100
MIN_RATING, MAX_RATING = 1, 5


def _load_ratings(path) -> dict[tuple[str, str], list[int]]:
    """(seller_id, sku) -> that product's ratings."""
    ratings: dict[tuple[str, str], list[int]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ratings[(row["seller_id"], row["sku"])].append(int(row["rating"]))
    return ratings


_RATINGS = _load_ratings(DEFAULT_REVIEWS_PATH)


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def get_review_summary(
    seller_id: str,
    has_reviews: bool | None = None,
    rating: int | None = None,
    max_avg_rating: float | None = None,
    limit: int = 20,
) -> dict:
    """One row per listing with its review count and ratings, filtered. Never raises.

    Filters combine (AND). `rating` keeps products with at least one review at exactly that
    rating; each row still reports the whole picture. Rows run lowest average first, products
    with no reviews last; `count` is every match, `items` is capped at `limit`.
    """
    for name, value in (("rating", rating), ("max_avg_rating", max_avg_rating)):
        if value is not None and not MIN_RATING <= value <= MAX_RATING:
            return _error("INVALID_RATING", f"{name} {value} is not a star rating. Give {MIN_RATING} to {MAX_RATING}.")
    if not 1 <= limit <= MAX_REVIEW_ITEMS:
        return _error("INVALID_LIMIT", f"{limit} is not a usable limit. Give a whole number from 1 to {MAX_REVIEW_ITEMS}.")

    rows = []
    for listing in listings_for(seller_id):
        given = _RATINGS.get((seller_id, listing.sku), [])
        avg = round(sum(given) / len(given), 2) if given else None
        if has_reviews is not None and bool(given) != has_reviews:
            continue
        if rating is not None and rating not in given:
            continue
        if max_avg_rating is not None and (avg is None or avg > max_avg_rating):
            continue
        rows.append(
            {
                "sku": listing.sku,
                "title": listing.title,
                "review_count": len(given),
                "avg_rating": avg,
                "lowest_rating": min(given) if given else None,
            }
        )

    rows.sort(key=lambda r: (r["avg_rating"] is None, r["avg_rating"] or 0, r["sku"]))
    return {
        "ok": True,
        "data": {"count": len(rows), "items": rows[:limit], "truncated": len(rows) > limit},
    }
