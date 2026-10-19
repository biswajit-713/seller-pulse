import json

from seller_pulse.guardrails import find_ungrounded

SOURCES = [json.dumps({"revenue": 4210.5, "previous_revenue": 3890})]


def test_derived_percent_is_sourced_forecast_is_not():
    answer = "Revenue $4,210.50, up 8.2% on $3,890.00. Expect $4,500 next week."
    assert find_ungrounded(answer, SOURCES) == ([], ["4,500"])


def test_underivable_percent_is_unsourced():
    assert find_ungrounded("Revenue $4,210.50, up 12%.", SOURCES) == ([], ["12"])


def test_derived_percent_needs_adjacent_sign():
    assert find_ungrounded("Up 8.2 points.", SOURCES) == ([], ["8.2"])


def test_negative_change_matches_absolute_value():
    assert find_ungrounded("Revenue down 7.6% to 3,890.", SOURCES) == ([], [])


def test_dates_are_not_percent_operands():
    assert find_ungrounded("Up 0.1%.", ["2026-09-27", "2026-09-28", "5"]) == ([], ["0.1"])


def test_ids_fabricated_and_unicode_hyphen():
    answer = "SKU‑1001 is fine; see REV-999 and REV-567, REV-999 again."
    assert find_ungrounded(answer, ["SKU-1001 REV-567"]) == (["REV-999"], [])


def test_unsourced_numbers_deduped_in_answer_order():
    assert find_ungrounded("1. 7 then 5 then 7.", ["nothing"]) == ([], ["7", "5"])
