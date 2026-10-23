from seller_pulse.agent import ToolCallRecord
from seller_pulse.chat import ChatResult
from seller_pulse.guardrails import GuardrailReport
from seller_pulse.memory import Preference
from seller_pulse.router import ALL_ROUTES, Route
from seller_pulse.trace_view import GUARDRAIL_PASSED, NO_PREFERENCES, NO_TOOL_CALLS, render_trace

SALES = ToolCallRecord("get_sales_analytics", {"period": "last_week"}, {"ok": True, "data": {"units": 904}})
INVENTORY = ToolCallRecord("check_inventory_status", {"sku": "SKU-1001"}, {"ok": True, "data": {}})
UNKNOWN = ToolCallRecord(
    "check_inventory_status",
    {"sku": "SKU-9999"},
    {"ok": False, "error": {"code": "UNKNOWN_SKU", "message": "no such SKU"}},
)
TONE = Preference("reply_tone", "short and warm", "2026-10-16T09:00:00+00:00", None)


def test_cached_record_is_marked_and_uncached_is_not():
    cached = ToolCallRecord("get_sales_analytics", {"period": "last_week"}, {"ok": True}, cached=True)
    assert render_trace(ChatResult(text="x", trace=[cached])).count("(cached)") == 1
    assert "(cached)" not in render_trace(ChatResult(text="x", trace=[SALES]))


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


def _report(**overrides) -> GuardrailReport:
    fields = dict(
        unverified_figures=[],
        ungrounded_ids=[],
        draft_pending=False,
        publish_claim=False,
        policy_refusal=False,
        policy_clauses=[],
    )
    return GuardrailReport(**(fields | overrides))


def _guardrail_section(report: GuardrailReport | None) -> str:
    out = render_trace(ChatResult(text="", trace=[], guardrail=report))
    return out.split("**Guardrail**\n", 1)[1]


def test_guardrail_none_and_untriggered_pass():
    assert _guardrail_section(None) == GUARDRAIL_PASSED
    assert _guardrail_section(_report()) == GUARDRAIL_PASSED


def test_guardrail_unverified_ids_and_figures():
    section = _guardrail_section(_report(ungrounded_ids=["SKU-1099"], unverified_figures=["4,500"]))
    assert section == "- ⚠ unverified: `SKU-1099`, `4,500`"


def test_guardrail_draft_pending():
    assert _guardrail_section(_report(draft_pending=True)) == "- ✎ draft pending your approval"


def test_guardrail_policy_refusal_lists_clauses():
    section = _guardrail_section(_report(policy_refusal=True, policy_clauses=["pol-2b", "pol-4a"]))
    assert section == "- ⛔ policy refusal `pol-2b` `pol-4a`"


def test_guardrail_publish_claim():
    assert _guardrail_section(_report(publish_claim=True)) == "- ⚠ publish claim corrected"


def test_guardrail_clause_cited_without_refusal_passes():
    assert _guardrail_section(_report(policy_clauses=["pol-2b"])) == GUARDRAIL_PASSED


def test_guardrail_multiple_triggers_one_line_each():
    section = _guardrail_section(_report(unverified_figures=["12"], draft_pending=True, publish_claim=True))
    assert section.splitlines() == [
        "- ⚠ unverified: `12`",
        "- ✎ draft pending your approval",
        "- ⚠ publish claim corrected",
    ]
