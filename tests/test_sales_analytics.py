from seller_pulse.sales import get_sales_analytics

SELLER = "SELLER-001"


def test_last_week_with_previous():  # SQ-01
    result = get_sales_analytics(SELLER, "last_week")
    assert result["ok"] is True
    data = result["data"]
    assert data["period"] == "last_week"
    assert (data["start"], data["end"]) == ("2026-09-14", "2026-09-20")
    assert (data["units_sold"], data["order_lines"], data["revenue_usd"]) == (904, 248, 41904.71)
    assert (data["days_in_window"], data["days_with_data"]) == (7, 7)
    prev = data["previous"]
    assert (prev["start"], prev["end"]) == ("2026-09-07", "2026-09-13")
    assert (prev["units_sold"], prev["order_lines"], prev["revenue_usd"]) == (1000, 267, 46283.07)
    assert prev["days_with_data"] == 7
    assert (data["data_start"], data["data_end"]) == ("2026-08-03", "2026-09-25")


def test_this_week_is_partly_covered():
    data = get_sales_analytics(SELLER, "this week")["data"]
    assert data["period"] == "this_week"
    assert (data["days_in_window"], data["days_with_data"]) == (7, 5)


def test_last_30_days_previous_is_partly_covered():
    prev = get_sales_analytics(SELLER, "last_30_days")["data"]["previous"]
    assert (prev["days_in_window"], prev["days_with_data"]) == (30, 25)


def test_single_day():  # SQ-17 fallback day
    data = get_sales_analytics(SELLER, "2026-09-25")["data"]
    assert (data["units_sold"], data["order_lines"], data["revenue_usd"]) == (142, 36, 6162.38)
    assert data["previous"]["start"] == data["previous"]["end"] == "2026-09-24"


def test_previous_is_null_before_data_start():
    data = get_sales_analytics(SELLER, "2026-08-03")["data"]
    assert data["previous"] is None


def test_no_data_is_not_zero():  # SQ-17
    result = get_sales_analytics(SELLER, "yesterday")
    assert result["ok"] is False
    assert result["error"]["code"] == "NO_DATA_FOR_PERIOD"
    assert "2026-09-25" in result["error"]["message"]
    assert "data" not in result


def test_invalid_period():
    result = get_sales_analytics(SELLER, "fortnight")
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_PERIOD"
    assert "last_week" in result["error"]["message"]


def test_unknown_seller_gets_no_data_and_no_hint():
    result = get_sales_analytics("SELLER-999", "last_week")
    assert result["error"]["code"] == "NO_DATA_FOR_PERIOD"
    assert "2026-09-25" not in result["error"]["message"]


def test_window_reaching_data_end_is_not_complete():  # SQ-09
    assert get_sales_analytics(SELLER, "2026-08-01..2026-08-31")["data"]["period_complete"] is True
    assert get_sales_analytics(SELLER, "this_month")["data"]["period_complete"] is False
    assert get_sales_analytics(SELLER, "2026-09-01..2026-09-25")["data"]["period_complete"] is False
