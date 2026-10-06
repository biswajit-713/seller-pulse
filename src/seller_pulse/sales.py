"""The sales domain.

`resolve_period` turns the `period` grammar from `docs/tools.md` §3 into an inclusive
`(start, end)` date pair, so aggregation never has to think about calendars. It is pure: no
CSV access, and `today` is a parameter rather than `date.today()` — the dataset is frozen, so
callers pass `date.fromisoformat(prompts.TODAY)`.

`get_sales_analytics` aggregates `sales.csv` over that window and returns the `docs/tools.md`
result envelope. The CSV is loaded once at import — same trade-off `inventory.py` documents:
a missing or malformed file fails at import, not at first call.
"""

import csv
from dataclasses import dataclass
from datetime import date, timedelta

from seller_pulse.config import DEFAULT_SALES_PATH
from seller_pulse.prompts import TODAY


class PeriodError(ValueError):
    """An unusable `period` string. The message reaches the LLM verbatim."""


PERIOD_GRAMMAR = (
    "today | yesterday | this_week | last_week | last_7_days | last_30_days | "
    "this_month | last_month | YYYY-MM-DD | YYYY-MM-DD..YYYY-MM-DD"
)


def _invalid(reason: str) -> PeriodError:
    return PeriodError(f"{reason} Accepted periods: {PERIOD_GRAMMAR}. Weeks run Mon–Sun.")


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise _invalid(f"'{text.strip()}' is not a valid YYYY-MM-DD date.") from None


def _keyword_window(keyword: str, today: date) -> tuple[date, date] | None:
    yesterday = today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    first_of_month = today.replace(day=1)
    match keyword:
        case "today":
            return today, today
        case "yesterday":
            return yesterday, yesterday
        case "this_week":
            return monday, today
        case "last_week":
            return monday - timedelta(days=7), monday - timedelta(days=1)
        case "last_7_days":
            return yesterday - timedelta(days=6), yesterday
        case "last_30_days":
            return yesterday - timedelta(days=29), yesterday
        case "this_month":
            return first_of_month, today
        case "last_month":
            last_of_prev = first_of_month - timedelta(days=1)
            return last_of_prev.replace(day=1), last_of_prev
    return None


def normalise_period(period: str) -> str:
    """Trim and lower-case; for keywords also turn spaces/hyphens into underscores.

    Dates are left alone, since that rewrite would mangle the hyphens in `YYYY-MM-DD`.
    """
    text = period.strip().lower()
    if text and text[0].isdigit():
        return text
    return text.replace(" ", "_").replace("-", "_")


def resolve_period(period: str, today: date) -> tuple[date, date]:
    """Resolve `period` to an inclusive `(start, end)` window, or raise `PeriodError`.

    Normalised first (see `normalise_period`), so `"last week"` works.
    """
    text = normalise_period(period)
    if not text:
        raise _invalid("Period is empty.")

    if text[0].isdigit():
        if ".." in text:
            start_text, _, end_text = text.partition("..")
            start, end = _parse_date(start_text), _parse_date(end_text)
        else:
            start = end = _parse_date(text)
    else:
        window = _keyword_window(text, today)
        if window is None:
            raise _invalid(f"Unknown period '{period.strip()}'.")
        start, end = window

    if start > end:
        raise _invalid(f"Start {start} is after end {end}.")
    if end > today:
        raise _invalid(f"End {end} is after today ({today}); there is no future data.")
    return start, end


@dataclass(frozen=True)
class SaleRow:
    seller_id: str
    date: date
    sku: str
    units_sold: int
    revenue_usd: float


def _load_sales(path) -> list[SaleRow]:
    with open(path, newline="", encoding="utf-8") as f:
        return [
            SaleRow(
                seller_id=row["seller_id"],
                date=date.fromisoformat(row["date"]),
                sku=row["sku"],
                units_sold=int(row["units_sold"]),
                revenue_usd=float(row["revenue_usd"]),
            )
            for row in csv.DictReader(f)
        ]


_SALES: list[SaleRow] = _load_sales(DEFAULT_SALES_PATH)


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _window_totals(rows: list[SaleRow], start: date, end: date) -> dict | None:
    """Totals for the inclusive window, or `None` if it has no rows (no data is not zero)."""
    in_window = [r for r in rows if start <= r.date <= end]
    if not in_window:
        return None
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        # Rounded once here, not per row.
        "revenue_usd": round(sum(r.revenue_usd for r in in_window), 2),
        "units_sold": sum(r.units_sold for r in in_window),
        "order_lines": len(in_window),
        "days_in_window": (end - start).days + 1,
        "days_with_data": len({r.date for r in in_window}),
    }


def get_sales_analytics(seller_id: str, period: str, *, today: date | None = None) -> dict:
    """Return the docs/tools.md envelope. Never raises for bad input."""
    today = today or date.fromisoformat(TODAY)
    try:
        start, end = resolve_period(period, today)
    except PeriodError as e:
        return _error("INVALID_PERIOD", str(e))

    # Tenant filter first: an unknown seller sees no rows, never another seller's.
    rows = [r for r in _SALES if r.seller_id == seller_id]
    current = _window_totals(rows, start, end)
    if current is None:
        window = f"{start.isoformat()}..{end.isoformat()}"
        if not rows:
            return _error("NO_DATA_FOR_PERIOD", f"No sales data for {window}. This seller has no sales data recorded.")
        last = max(r.date for r in rows).isoformat()
        return _error("NO_DATA_FOR_PERIOD", f"No sales data for {window}. The last date with sales data is {last}.")

    length = end - start
    prev_end = start - timedelta(days=1)
    data_end = max(r.date for r in rows)
    return {
        "ok": True,
        "data": {
            "period": normalise_period(period),
            **current,
            # A window reaching the last recorded date is still filling in. `previous` always
            # ends before `start`, so it is complete whenever it exists.
            "period_complete": end < data_end,
            "previous": _window_totals(rows, prev_end - length, prev_end),
            "data_start": min(r.date for r in rows).isoformat(),
            "data_end": data_end.isoformat(),
        },
    }
