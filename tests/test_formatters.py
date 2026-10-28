from datetime import date

import pytest

from seller_pulse.agent import ToolCallRecord
from seller_pulse.formatters import render_answer
from seller_pulse.guardrails import check_output
from seller_pulse.inventory import check_inventory_status, list_low_stock
from seller_pulse.memory import Preference
from seller_pulse.router import Route
from seller_pulse.sales import get_sales_analytics, get_top_products

SELLER = "SELLER-001"
TODAY = date(2026, 9, 27)


def _record(name: str, args: dict, result: dict) -> ToolCallRecord:
    return ToolCallRecord(name=name, args=args, result=result)


def _render(name: str, args: dict, result: dict, preferences=()) -> str:
    text = render_answer([_record(name, args, result)], list(preferences))
    assert text is not None
    # Every rendered answer must clear the guardrail against the call it was rendered from.
    report = check_output(
        text,
        trace=[_record(name, args, result)],
        retrieved_context="",
        query="",
        preferences=list(preferences),
        routes={Route.DATA},
    )
    assert not report.triggered, (report.unverified_figures, report.ungrounded_ids)
    return text


def test_top_products_partial_period():
    args = {"period": "last_30_days", "metric": "revenue", "limit": 1}
    text = _render("get_top_products", args, get_top_products(SELLER, **args, today=TODAY))
    assert text == (
        "**Top products by revenue, last 30 days (2026-08-28 to 2026-09-26)**\n\n"
        "1. SKU-1036 — Handwoven Wool Area Rug 4x6: 116 units, $12,679.96\n\n"
        "Showing the top results only; 147 products had sales in this window.\n\n"
        "Note: data covers 29 of 30 days; the period is partial (data through 2026-09-25)."
    )


def test_same_result_renders_identically():
    args = {"period": "last_30_days", "metric": "units", "limit": 3}
    result = get_top_products(SELLER, **args, today=TODAY)
    assert _render("get_top_products", args, result) == _render("get_top_products", args, result)


def test_sales_with_trend():
    args = {"period": "last_week"}
    text = _render("get_sales_analytics", args, get_sales_analytics(SELLER, "last_week", today=TODAY))
    assert text == (
        "**Sales, last week (2026-09-14 to 2026-09-20)**\n\n"
        "- Revenue: $41,904.71\n- Units sold: 904\n- Order lines: 248\n\n"
        "Compared with 2026-09-07 to 2026-09-13: revenue down 9.5% ($46,283.07), "
        "units down 9.6% (1,000)."
    )


def test_sales_sku_with_unequal_coverage_prints_no_percentage():
    result = get_sales_analytics(SELLER, "last_30_days", "SKU-1036", today=TODAY)
    text = _render("get_sales_analytics", {"period": "last_30_days", "sku": "SKU-1036"}, result)
    assert text.startswith("**Sales for SKU-1036, last 30 days")
    assert "%" not in text
    assert "isn't a like-for-like comparison" in text


def test_low_stock_flags_active_without_stock_and_truncation():
    result = list_low_stock(SELLER, 5)
    text = _render("list_low_stock", {"threshold": 5}, result)
    assert text.startswith("**Low stock, at or below 5 units**")
    assert "- SKU-1013 — Industrial Sconce Wall Sconce: 0 in stock (Active). Active with no stock" in text
    assert "58 listings match; showing the lowest only." in text


def test_low_stock_empty():
    text = _render("list_low_stock", {"threshold": 0}, {"ok": True, "data": {"threshold": 0, "count": 0, "items": [], "truncated": False}})
    assert text == "No listings are at or below 0 units."


def test_inventory_applies_saved_restock_threshold():
    pref = Preference(key="restock_threshold", value="5", updated_at="2026-09-01", previous_value=None)
    text = _render("check_inventory_status", {"sku": "SKU-1013"}, check_inventory_status(SELLER, "SKU-1013"), [pref])
    assert "- Price: $75.60" in text
    assert "an inconsistency to fix" in text
    assert "At or below your restock threshold (5): time to restock." in text


def test_not_rendered_when_not_a_lone_successful_formattable_call():
    ok = get_top_products(SELLER, "last_30_days", today=TODAY)
    top = _record("get_top_products", {"period": "last_30_days"}, ok)
    failed = _record("get_sales_analytics", {"period": "x"}, {"ok": False, "error": {"code": "INVALID_PERIOD", "message": "m"}})
    other = _record("find_listing", {"name": "boho"}, {"ok": True, "data": {"matches": []}})
    assert render_answer([], []) is None
    assert render_answer([top, top], []) is None
    assert render_answer([failed], []) is None
    assert render_answer([other], []) is None


@pytest.mark.parametrize("result", [{"ok": True, "data": {}}, {"ok": True, "data": {"items": None}}])
def test_malformed_result_falls_back_to_model_text(result):
    assert render_answer([_record("get_top_products", {}, result)], []) is None
