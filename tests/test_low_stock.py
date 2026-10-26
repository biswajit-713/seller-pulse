import csv

from seller_pulse.config import DEFAULT_LISTINGS_PATH
from seller_pulse.inventory import MAX_LOW_STOCK, list_low_stock

SELLER = "SELLER-001"


def _rows(threshold: int) -> list[dict]:
    with open(DEFAULT_LISTINGS_PATH, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if int(r["stock_qty"]) <= threshold]


def test_returns_only_listings_at_or_below_threshold_lowest_first():
    result = list_low_stock(SELLER, 5)
    assert result["ok"]
    data = result["data"]
    expected = _rows(5)
    assert data["count"] == len(expected)
    qtys = [i["stock_qty"] for i in data["items"]]
    assert qtys == sorted(qtys) and all(q <= 5 for q in qtys)
    assert data["items"][0].keys() == {"sku", "title", "stock_qty", "status"}


def test_threshold_is_inclusive():
    # SKU-1001 has stock_qty 6: counted at 6, not at 5.
    assert list_low_stock(SELLER, 6)["data"]["count"] > list_low_stock(SELLER, 5)["data"]["count"]


def test_active_zero_stock_reported_verbatim():
    items = {i["sku"]: i for i in list_low_stock(SELLER, 0)["data"]["items"]}
    assert items["SKU-1013"]["status"] == "Active" and items["SKU-1013"]["stock_qty"] == 0
    assert items["SKU-1002"]["status"] == "Out of Stock"


def test_items_capped_with_full_count():
    data = list_low_stock(SELLER, 10**6)["data"]
    assert len(data["items"]) == MAX_LOW_STOCK and data["truncated"] is True
    assert data["count"] > MAX_LOW_STOCK


def test_negative_threshold_is_invalid():
    assert list_low_stock(SELLER, -1)["error"]["code"] == "INVALID_THRESHOLD"


def test_other_seller_sees_nothing():
    assert list_low_stock("SELLER-999", 10**6)["data"] == {
        "threshold": 10**6, "count": 0, "items": [], "truncated": False
    }
