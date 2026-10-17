from seller_pulse.agent import ToolCallRecord
from seller_pulse.chat import ChatResult
from seller_pulse.memory import Preference
from seller_pulse.router import ALL_ROUTES, Route
from seller_pulse.trace_view import NO_PREFERENCES, NO_TOOL_CALLS, render_trace

SALES = ToolCallRecord("get_sales_analytics", {"period": "last_week"}, {"ok": True, "data": {"units": 904}})
INVENTORY = ToolCallRecord("check_inventory_status", {"sku": "SKU-1001"}, {"ok": True, "data": {}})
UNKNOWN = ToolCallRecord(
    "check_inventory_status",
    {"sku": "SKU-9999"},
    {"ok": False, "error": {"code": "UNKNOWN_SKU", "message": "no such SKU"}},
)
TONE = Preference("reply_tone", "short and warm", "2026-10-16T09:00:00+00:00", None)


def test_two_calls_routes_and_preference():
    out = render_trace(
        ChatResult(text="", trace=[SALES, INVENTORY], routes=frozenset({Route.DATA}), preferences=[TONE])
    )
    assert "**Routes:** data" in out
    assert '`get_sales_analytics` `{"period": "last_week"}` — ✓ ok' in out
    assert '`check_inventory_status` `{"sku": "SKU-1001"}` — ✓ ok' in out
    assert "`reply_tone` → `short and warm`" in out
    assert "904" not in out  # result payload is not shown


def test_fallback_is_marked():
    out = render_trace(ChatResult(text="", trace=[], routes=ALL_ROUTES, route_fallback=True))
    assert "(fallback: all routes)" in out


def test_empty_renders_none_lines():
    out = render_trace(ChatResult(text="", trace=[]))
    assert "**Routes:** none" in out
    assert NO_TOOL_CALLS in out
    assert NO_PREFERENCES in out
    assert "fallback" not in out


def test_error_envelope_shows_code():
    out = render_trace(ChatResult(text="", trace=[UNKNOWN], routes=frozenset({Route.DATA})))
    assert "✗ `UNKNOWN_SKU`" in out


def test_backticks_cannot_break_code_spans():
    pref = Preference("reply_tone", "use `code` style", "2026-10-16T09:00:00+00:00", None)
    out = render_trace(ChatResult(text="", trace=[], preferences=[pref]))
    assert "`use 'code' style`" in out
