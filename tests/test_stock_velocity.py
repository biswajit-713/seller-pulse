from seller_pulse.sales import MAX_TOP_PRODUCTS, get_stock_velocity

SELLER = "SELLER-001"
WINDOW = "2026-08-27..2026-09-25"


def test_nearly_gone_ordered_by_units_sold():
    data = get_stock_velocity(SELLER, WINDOW, min_stock=1, max_stock=1)["data"]
    assert data["count"] == 6
    assert [(i["sku"], i["units_sold"]) for i in data["items"]] == [
        ("SKU-1018", 25), ("SKU-1019", 6), ("SKU-1130", 6),
        ("SKU-1083", 5), ("SKU-1029", 3), ("SKU-1125", 2),
    ]


def test_slow_movers_carrying_stock():
    data = get_stock_velocity(SELLER, "2026-08-03..2026-09-25", min_stock=20, order="slowest", limit=8)["data"]
    assert [(i["sku"], i["units_sold"], i["stock_qty"]) for i in data["items"]] == [
        ("SKU-1095", 1, 42), ("SKU-1050", 2, 22), ("SKU-1097", 3, 37), ("SKU-1064", 4, 35),
        ("SKU-1022", 5, 51), ("SKU-1052", 5, 51), ("SKU-1081", 5, 26), ("SKU-1150", 5, 47),
    ]
    assert data["shown_stock_value_usd"] == 12464.81 and data["truncated"] is True
    assert data["items"][0]["stock_value_usd"] == 2795.52


def test_unsold_listing_appears_with_zero_units():
    data = get_stock_velocity(SELLER, "last_7_days", min_stock=1, order="slowest", limit=MAX_TOP_PRODUCTS)["data"]
    assert data["items"][0]["units_sold"] == 0


def test_validation_and_tenancy():
    assert get_stock_velocity(SELLER, WINDOW, min_stock=-1)["error"]["code"] == "INVALID_STOCK_RANGE"
    assert get_stock_velocity(SELLER, WINDOW, min_stock=5, max_stock=1)["error"]["code"] == "INVALID_STOCK_RANGE"
    assert get_stock_velocity(SELLER, WINDOW, order="best")["error"]["code"] == "INVALID_ORDER"
    assert get_stock_velocity(SELLER, WINDOW, limit=0)["error"]["code"] == "INVALID_LIMIT"
    assert get_stock_velocity(SELLER, "nonsense")["error"]["code"] == "INVALID_PERIOD"
    assert get_stock_velocity("SELLER-999", WINDOW)["error"]["code"] == "NO_DATA_FOR_PERIOD"


def test_max_units_sold_zero_returns_only_unsold():
    data = get_stock_velocity(SELLER, "2026-09-01..2026-09-25", max_units_sold=0, limit=MAX_TOP_PRODUCTS)["data"]
    assert data["count"] == 4 and data["truncated"] is False
    assert sorted(i["sku"] for i in data["items"]) == ["SKU-1040", "SKU-1050", "SKU-1095", "SKU-1120"]
    assert all(i["units_sold"] == 0 for i in data["items"])


def test_negative_max_units_sold_rejected():
    assert get_stock_velocity(SELLER, WINDOW, max_units_sold=-1)["error"]["code"] == "INVALID_MAX_UNITS_SOLD"
