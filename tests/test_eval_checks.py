import pytest

from seller_pulse.agent import ToolCallRecord
from seller_pulse.evals.checks import CheckKind, Dimension, check_traceable, run_checks
from seller_pulse.prompts import SYSTEM_PROMPT

SALES = "get_sales_analytics"
LAST_WEEK = ToolCallRecord(
    name=SALES,
    args={"period": "last_week"},
    result={"ok": True, "data": {"orders": 904, "revenue": 41904.71}},
)


def _one(check, answer="", trace=()):
    [result] = run_checks([check], answer, list(trace))
    return result


# --- tool_called / no_tool_called


def test_tool_called_pass_and_fail():
    check = {"kind": "tool_called", "name": SALES}
    assert _one(check, trace=[LAST_WEEK]).passed
    assert not _one(check).passed


def test_tool_called_args_match_on_second_call():
    first = ToolCallRecord(name=SALES, args={"period": "this_month"}, result={})
    check = {"kind": "tool_called", "name": SALES, "args": {"period": ["Last_Week ", "last_7_days"]}}
    assert _one(check, trace=[first, LAST_WEEK]).passed
    assert not _one(check, trace=[first]).passed


def test_no_tool_called_pass_and_fail():
    assert _one({"kind": "no_tool_called"}).passed
    assert not _one({"kind": "no_tool_called"}, trace=[LAST_WEEK]).passed
    named = {"kind": "no_tool_called", "name": "check_inventory_status"}
    assert _one(named, trace=[LAST_WEEK]).passed
    assert not _one({"kind": "no_tool_called", "name": SALES}, trace=[LAST_WEEK]).passed


# --- contains_all / contains_any / not_contains_pattern


def test_contains_all_pass_and_fail():
    check = {"kind": "contains_all", "needles": ["904", "41,904.71", "rev-567"]}
    assert _one(check, "904 orders, $41,904.71 revenue; see REV-567.").passed
    assert not _one(check, "904 orders, $41,904.71 revenue.").passed


def test_number_normalisation():
    assert _one({"kind": "contains_all", "needles": ["41904.71"]}, "Revenue was $41,904.71.").passed
    assert _one({"kind": "contains_all", "needles": ["1,000"]}, "1000 orders").passed
    assert _one({"kind": "contains_all", "needles": ["1000"]}, "$1,000.00 total").passed
    assert not _one({"kind": "contains_all", "needles": ["904"]}, "9045 orders").passed
    assert not _one({"kind": "contains_all", "needles": ["904"]}, "$41904.71").passed


def test_contains_any_alternate_anchoring_alone():
    check = {"kind": "contains_any", "groups": [["904", "41,904.71"], ["763", "34,731.54"]]}
    assert _one(check, "Last 7 days: 763 orders, $34,731.54.").passed
    assert not _one(check, "Last 7 days: 763 orders.").passed


def test_not_contains_pattern_pass_and_fail():
    check = {"kind": "not_contains_pattern", "pattern": r"~\s?\$\s?\d"}
    assert _one(check, "I can't forecast next week.").passed
    assert not _one(check, "Next week will be ~$40k.").passed


# --- validation and dimensions


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        run_checks([{"kind": "regex_match"}], "", [])
    with pytest.raises(ValueError):  # automatic only, never written in the case file
        run_checks([{"kind": "traceable"}], "", [])


def test_dimensions_default_override_and_behavior_raises():
    results = run_checks(
        [
            {"kind": "tool_called", "name": SALES},
            {"kind": "no_tool_called"},
            {"kind": "contains_all", "needles": []},
            {"kind": "contains_any", "groups": [[]]},
            {"kind": "not_contains_pattern", "pattern": "x"},
            {"kind": "contains_all", "needles": [], "dimension": "grounded"},
        ],
        "",
        [],
    )
    assert [r.dimension for r in results] == [
        Dimension.TOOL_USE, Dimension.TOOL_USE, Dimension.ACCURACY,
        Dimension.ACCURACY, Dimension.GROUNDED, Dimension.GROUNDED,
    ]
    assert results[0].kind is CheckKind.TOOL_CALLED
    with pytest.raises(ValueError):
        run_checks([{"kind": "contains_all", "needles": [], "dimension": "behavior"}], "", [])
    with pytest.raises(ValueError):
        run_checks([{"kind": "contains_all", "needles": [], "dimension": "style"}], "", [])


# --- traceable


def _traceable(answer, trace=(LAST_WEEK,), context="", query="How did last week go?", **kw):
    return check_traceable(answer, trace=list(trace), retrieved_context=context, query=query, **kw)


def test_traceable_ids():
    context = "[review REV-567 · SKU-1036 · 2★]"
    ok = _traceable("See rev-567 on SKU-1036.", context=context)
    assert ok.check.passed and ok.check.kind is CheckKind.TRACEABLE and ok.check.dimension is Dimension.GROUNDED
    bad = _traceable("See REV-567 and REV-999.", context=context)
    assert not bad.check.passed
    assert bad.untraced_ids == ["REV-999"]


def test_traceable_suspects():
    answer = (
        "As of 2026-09-27:\n"
        "1. Revenue $41,904.71 on 904 orders, up 9.6%.\n"
        "2. SKU-1036 is fine.\n"
    )
    result = _traceable(answer, context="SKU-1036")
    assert result.check.passed
    assert result.suspects == ["9.6"]


def test_traceable_query_context_and_allow():
    result = _traceable(
        "Delivery took 3 weeks; 12 units.",
        query_context="delivery took almost 3 weeks",
        allow=["12"],
    )
    assert result.suspects == []


def test_traceable_system_prompt_wording_is_not_a_source():
    # 2026-09-14 is in the prompt's example wording; only its stated dates are sources.
    assert "2026-09-14" in SYSTEM_PROMPT
    result = _traceable("Data starts 2026-08-03; week of 2026-09-14.", trace=[])
    assert result.suspects == ["2026-09-14"]
