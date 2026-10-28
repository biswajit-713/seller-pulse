import csv
from collections import defaultdict

import pytest

from seller_pulse.config import DEFAULT_LISTINGS_PATH, DEFAULT_REVIEWS_PATH
from seller_pulse.reviews import MAX_REVIEW_ITEMS, get_review_summary

SELLER = "SELLER-001"


def _csv(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ratings() -> dict[str, list[int]]:
    by_sku: dict[str, list[int]] = defaultdict(list)
    for r in _csv(DEFAULT_REVIEWS_PATH):
        by_sku[r["sku"]].append(int(r["rating"]))
    return by_sku


def _skus(result) -> set[str]:
    return {i["sku"] for i in result["data"]["items"]}


def test_unreviewed_listings_are_the_set_difference():
    unreviewed = {r["sku"] for r in _csv(DEFAULT_LISTINGS_PATH)} - set(_ratings())
    data = get_review_summary(SELLER, has_reviews=False, limit=MAX_REVIEW_ITEMS)["data"]
    assert data["count"] == len(unreviewed) and not data["truncated"]
    assert {i["sku"] for i in data["items"]} == unreviewed
    assert all(i["review_count"] == 0 and i["avg_rating"] is None for i in data["items"])


def test_rating_filter_keeps_skus_with_at_least_one_review_at_that_rating():
    expected = {sku for sku, rs in _ratings().items() if 1 in rs}
    result = get_review_summary(SELLER, rating=1, limit=MAX_REVIEW_ITEMS)
    assert result["ok"] and _skus(result) == expected
    # The row still reports the whole picture, not just the matching reviews.
    item = result["data"]["items"][0]
    rs = _ratings()[item["sku"]]
    assert item["review_count"] == len(rs) and item["lowest_rating"] == min(rs)
    assert item["avg_rating"] == round(sum(rs) / len(rs), 2) and item["title"]


def test_max_avg_rating_filter_and_lowest_average_first():
    items = get_review_summary(SELLER, max_avg_rating=2, limit=MAX_REVIEW_ITEMS)["data"]["items"]
    assert items and all(i["avg_rating"] <= 2 for i in items)
    avgs = [i["avg_rating"] for i in items]
    assert avgs == sorted(avgs)


def test_filters_combine():
    both = get_review_summary(SELLER, rating=1, max_avg_rating=1, limit=MAX_REVIEW_ITEMS)["data"]["items"]
    assert both and all(i["avg_rating"] == 1 for i in both)


def test_no_filters_covers_catalogue_with_unreviewed_last():
    data = get_review_summary(SELLER, limit=MAX_REVIEW_ITEMS)["data"]
    assert data["count"] == len(_csv(DEFAULT_LISTINGS_PATH))
    counts = [i["review_count"] for i in data["items"]]
    first_zero = counts.index(0)
    assert all(c == 0 for c in counts[first_zero:]) and all(c > 0 for c in counts[:first_zero])


def test_items_capped_with_full_count():
    data = get_review_summary(SELLER, has_reviews=False, limit=5)["data"]
    assert len(data["items"]) == 5 and data["count"] > 5 and data["truncated"]


def test_has_reviews_true_excludes_unreviewed():
    data = get_review_summary(SELLER, has_reviews=True, limit=MAX_REVIEW_ITEMS)["data"]
    assert data["count"] == len(_ratings())


@pytest.mark.parametrize("kwargs, code", [
    ({"rating": 0}, "INVALID_RATING"),
    ({"rating": 6}, "INVALID_RATING"),
    ({"max_avg_rating": 0.5}, "INVALID_RATING"),
    ({"limit": 0}, "INVALID_LIMIT"),
    ({"limit": MAX_REVIEW_ITEMS + 1}, "INVALID_LIMIT"),
])
def test_invalid_arguments(kwargs, code):
    result = get_review_summary(SELLER, **kwargs)
    assert result["ok"] is False and result["error"]["code"] == code


def test_other_seller_sees_nothing():
    data = get_review_summary("SELLER-999")["data"]
    assert data["count"] == 0 and data["items"] == []
