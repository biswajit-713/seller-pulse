import csv
from collections import defaultdict

from seller_pulse.config import DEFAULT_SALES_PATH
from seller_pulse.sales import MAX_TOP_PRODUCTS, get_top_products

SELLER = "SELLER-001"


def _expected(start: str, end: str, key) -> list[tuple[str, float]]:
    totals: dict[str, float] = defaultdict(float)
    with open(DEFAULT_SALES_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if start <= r["date"] <= end:
                totals[r["sku"]] += key(r)
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))


def test_ranks_by_revenue_by_default():
    result = get_top_products(SELLER, "2026-09-14..2026-09-20", limit=3)
    assert result["ok"]
    data = result["data"]
    expected = _expected("2026-09-14", "2026-09-20", lambda r: float(r["revenue_usd"]))
    assert [i["sku"] for i in data["items"]] == [sku for sku, _ in expected[:3]]
    assert data["items"][0]["revenue_usd"] == round(expected[0][1], 2)
    assert data["metric"] == "revenue" and data["count"] == len(expected) and data["truncated"]
    assert data["items"][0]["title"]


def test_ranks_by_units():
    data = get_top_products(SELLER, "last_week", "units", 2)["data"]
    expected = _expected("2026-09-14", "2026-09-20", lambda r: int(r["units_sold"]))
    assert [i["sku"] for i in data["items"]] == [sku for sku, _ in expected[:2]]
    assert data["items"][0]["units_sold"] == expected[0][1]


def test_window_fields_match_sales_analytics():
    data = get_top_products(SELLER, "this week")["data"]
    assert (data["days_in_window"], data["days_with_data"]) == (7, 5)
    assert data["data_end"] == "2026-09-25" and data["period_complete"] is False


def test_errors():
    assert get_top_products(SELLER, "last_week", "profit")["error"]["code"] == "INVALID_METRIC"
    assert get_top_products(SELLER, "last_week", limit=0)["error"]["code"] == "INVALID_LIMIT"
    assert get_top_products(SELLER, "last_week", limit=MAX_TOP_PRODUCTS + 1)["error"]["code"] == "INVALID_LIMIT"
    assert get_top_products(SELLER, "someday")["error"]["code"] == "INVALID_PERIOD"
    assert get_top_products(SELLER, "2026-01-01")["error"]["code"] == "NO_DATA_FOR_PERIOD"


def test_unknown_seller_sees_nothing():
    assert get_top_products("SELLER-999", "last_week")["error"]["code"] == "NO_DATA_FOR_PERIOD"
