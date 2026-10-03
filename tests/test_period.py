from datetime import date

import pytest

from seller_pulse.sales import PERIOD_GRAMMAR, PeriodError, resolve_period

TODAY = date(2026, 9, 27)  # a Sunday


@pytest.mark.parametrize(
    "period, start, end",
    [
        ("today", "2026-09-27", "2026-09-27"),
        ("yesterday", "2026-09-26", "2026-09-26"),
        ("this_week", "2026-09-21", "2026-09-27"),
        ("last_week", "2026-09-14", "2026-09-20"),
        ("last_7_days", "2026-09-20", "2026-09-26"),
        ("last_30_days", "2026-08-28", "2026-09-26"),
        ("this_month", "2026-09-01", "2026-09-27"),
        ("last_month", "2026-08-01", "2026-08-31"),
        ("2026-09-05", "2026-09-05", "2026-09-05"),
        ("2026-09-01..2026-09-10", "2026-09-01", "2026-09-10"),
    ],
)
def test_resolves(period, start, end):
    assert resolve_period(period, TODAY) == (date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize("period", ["last week", "Last-Week", "  LAST_WEEK  "])
def test_keyword_normalisation(period):
    assert resolve_period(period, TODAY) == (date(2026, 9, 14), date(2026, 9, 20))


def test_weekday_today_anchors_this_week_on_monday():
    wednesday = date(2026, 9, 23)
    assert resolve_period("this_week", wednesday) == (date(2026, 9, 21), wednesday)
    assert resolve_period("last_week", wednesday) == (date(2026, 9, 14), date(2026, 9, 20))


def test_last_month_across_year_boundary():
    assert resolve_period("last_month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))


@pytest.mark.parametrize(
    "period",
    ["next week", "2026-13-01", "2026-09-10..2026-09-01", "2026-10-05", "", "2026-09-01..oops"],
)
def test_rejects(period):
    with pytest.raises(PeriodError) as exc:
        resolve_period(period, TODAY)
    assert PERIOD_GRAMMAR in str(exc.value)
