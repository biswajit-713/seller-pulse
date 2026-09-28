"""Computed review statistics — SQ-12 and SQ-13, answered by aggregation, not retrieval.

Dense top-k cannot answer "what are buyers complaining about most?" or "which product has my
worst reviews?": a question *about* complaints is not textually close to a complaint (measured:
top-k for the former surfaces a 5-star review at 0.762), and a group-by-SKU mean over all 111
reviews is an aggregation, not a neighbourhood. Both are exact metadata scans against
`seller_reviews` instead.

Every figure here is computed in Python and handed to the model as a fact — never counted by
the model itself. An LLM asked to tally 111 ratings will produce a plausible distribution that
is quietly wrong, and guardrail §5 (`docs/requirements.md`) forbids stating a figure not
returned by a live source.

`catalog_size` is the one value sourced outside the vector store: `inventory.catalog_size()`,
i.e. `len(inventory._LISTINGS)`. Listings are deliberately not embedded (`rag-00` decision #2),
so the review store only knows how many SKUs *have* reviews, never how many exist. Without this,
SQ-13's sample-size caveat degrades from "65 of your 150 SKUs have none" to "of the 85 that have
reviews...", the weaker half of the warning.

`per_sku` deliberately includes single-review SKUs — filtering them out here would hide the
distribution from the renderer. A 1-review SKU at 1.0 legitimately outranks a 2-review SKU at
2.0 on mean alone; it is the renderer's and prompt's job to frame `n == 1` rows as low-evidence,
not this module's job to drop them.
"""

from collections import Counter
from dataclasses import dataclass

from seller_pulse import inventory
from seller_pulse.rag.retrieval import Hit, ReviewStore


@dataclass(frozen=True)
class SkuStats:
    sku: str
    title: str
    n: int
    mean: float
    review_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReviewStats:
    total: int
    distribution: dict[int, int]
    mean: float
    low_rated: tuple[Hit, ...]
    per_sku: tuple[SkuStats, ...]
    skus_with_reviews: int
    catalog_size: int
    skus_without_reviews: int
    review_count_histogram: dict[int, int]


def compute(reviews: ReviewStore) -> ReviewStats:
    all_hits = reviews.all_reviews()
    low_rated = reviews.low_rated()

    total = len(all_hits)
    ratings = [hit.metadata["rating"] for hit in all_hits]
    distribution = dict(sorted(Counter(ratings).items()))
    mean = sum(ratings) / total

    by_sku: dict[str, list[Hit]] = {}
    for hit in all_hits:
        by_sku.setdefault(hit.metadata["sku"], []).append(hit)

    per_sku = tuple(
        sorted(
            (
                SkuStats(
                    sku=sku,
                    title=hits[0].metadata["title"],
                    n=len(hits),
                    mean=sum(hit.metadata["rating"] for hit in hits) / len(hits),
                    review_ids=tuple(hit.id for hit in hits),
                )
                for sku, hits in by_sku.items()
            ),
            key=lambda s: (s.mean, -s.n, s.sku),
        )
    )

    skus_with_reviews = len(by_sku)
    catalog_size = inventory.catalog_size()
    skus_without_reviews = catalog_size - skus_with_reviews
    review_count_histogram = dict(sorted(Counter(s.n for s in per_sku).items()))

    return ReviewStats(
        total=total,
        distribution=distribution,
        mean=round(mean, 2),
        low_rated=tuple(low_rated),
        per_sku=per_sku,
        skus_with_reviews=skus_with_reviews,
        catalog_size=catalog_size,
        skus_without_reviews=skus_without_reviews,
        review_count_histogram=review_count_histogram,
    )
