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
from seller_pulse.inventory import SKU_PATTERN, get_listing, normalise_sku
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


def _window_totals(
    rows: list[SaleRow], start: date, end: date, sku: str | None = None
) -> dict | None:
    """Totals for the inclusive window, or `None` if the seller has no rows in it (no data is
    not zero). With `sku`, the figures cover that SKU only, while `days_with_data` still counts
    the seller's recorded days: a SKU with no sales on a recorded day sold zero, not unknown."""
    in_window = [r for r in rows if start <= r.date <= end]
    if not in_window:
        return None
    recorded_days = {r.date for r in in_window}
    if sku is not None:
        in_window = [r for r in in_window if r.sku == sku]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        # Rounded once here, not per row.
        "revenue_usd": round(sum(r.revenue_usd for r in in_window), 2),
        "units_sold": sum(r.units_sold for r in in_window),
        "order_lines": len(in_window),
        "days_in_window": (end - start).days + 1,
        "days_with_data": len(recorded_days),
    }


def get_sales_analytics(
    seller_id: str, period: str, sku: str | None = None, *, today: date | None = None
) -> dict:
    """Return the docs/tools.md envelope. Never raises for bad input.

    `sku` narrows revenue, units and order lines to one listing; omitted, they cover the seller.
    """
    today = today or date.fromisoformat(TODAY)
    if sku is not None:
        sku = normalise_sku(sku)
        if not SKU_PATTERN.match(sku):
            return _error("INVALID_SKU", f"'{sku}' is not a SKU. Expected the form SKU-1234.")
        listing = get_listing(sku)
        # Another tenant's SKU is reported as unknown, so the error never reveals it exists.
        if listing is None or listing.seller_id != seller_id:
            return _error("UNKNOWN_SKU", f"{sku} is not in your catalog.")
    try:
        start, end = resolve_period(period, today)
    except PeriodError as e:
        return _error("INVALID_PERIOD", str(e))

    # Tenant filter first: an unknown seller sees no rows, never another seller's.
    rows = [r for r in _SALES if r.seller_id == seller_id]
    current = _window_totals(rows, start, end, sku)
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
            **({"sku": sku} if sku else {}),
            **current,
            # A window reaching the last recorded date is still filling in. `previous` always
            # ends before `start`, so it is complete whenever it exists.
            "period_complete": end < data_end,
            "previous": _window_totals(rows, prev_end - length, prev_end, sku),
            "data_start": min(r.date for r in rows).isoformat(),
            "data_end": data_end.isoformat(),
        },
    }


TOP_PRODUCT_METRICS = ("revenue", "units")
TOP_PRODUCT_GROUPS = ("sku", "category")
UNCATEGORISED = "Uncategorised"
MAX_TOP_PRODUCTS = 20


def get_top_products(
    seller_id: str,
    period: str,
    metric: str = "revenue",
    limit: int = 5,
    group_by: str = "sku",
    *,
    today: date | None = None,
) -> dict:
    """The seller's best sellers for one window, ranked by `metric`. Never raises.

    `group_by` is `sku` (one item per listing) or `category` (listings summed per category).
    Ties break on the SKU or category name so the order is stable. The window fields mirror `get_sales_analytics`
    (`days_with_data`, `period_complete`, `data_end`) so the same caveats apply.
    """
    metric = metric.strip().lower()
    if metric not in TOP_PRODUCT_METRICS:
        return _error("INVALID_METRIC", f"'{metric}' is not a metric. Accepted: {' | '.join(TOP_PRODUCT_METRICS)}.")
    group_by = group_by.strip().lower()
    if group_by not in TOP_PRODUCT_GROUPS:
        return _error("INVALID_GROUP_BY", f"'{group_by}' is not a grouping. Accepted: {' | '.join(TOP_PRODUCT_GROUPS)}.")
    if not 1 <= limit <= MAX_TOP_PRODUCTS:
        return _error("INVALID_LIMIT", f"{limit} is not a usable limit. Give a whole number from 1 to {MAX_TOP_PRODUCTS}.")
    today = today or date.fromisoformat(TODAY)
    try:
        start, end = resolve_period(period, today)
    except PeriodError as e:
        return _error("INVALID_PERIOD", str(e))

    rows = [r for r in _SALES if r.seller_id == seller_id]
    in_window = [r for r in rows if start <= r.date <= end]
    if not in_window:
        window = f"{start.isoformat()}..{end.isoformat()}"
        if not rows:
            return _error("NO_DATA_FOR_PERIOD", f"No sales data for {window}. This seller has no sales data recorded.")
        last = max(r.date for r in rows).isoformat()
        return _error("NO_DATA_FOR_PERIOD", f"No sales data for {window}. The last date with sales data is {last}.")

    per_key: dict[str, dict] = {}
    for r in in_window:
        listing = get_listing(r.sku)
        key_name = r.sku if group_by == "sku" else (listing.category if listing else UNCATEGORISED)
        agg = per_key.setdefault(key_name, {"units_sold": 0, "revenue_usd": 0.0})
        agg["units_sold"] += r.units_sold
        agg["revenue_usd"] += r.revenue_usd
    key = "revenue_usd" if metric == "revenue" else "units_sold"
    ranked = sorted(per_key.items(), key=lambda kv: (-kv[1][key], kv[0]))
    data_end = max(r.date for r in rows)
    items = []
    for name, agg in ranked[:limit]:
        if group_by == "sku":
            listing = get_listing(name)
            label = {"sku": name, "title": listing.title if listing else None}
        else:
            label = {"category": name}
        items.append({**label, "units_sold": agg["units_sold"], "revenue_usd": round(agg["revenue_usd"], 2)})
    return {
        "ok": True,
        "data": {
            "period": normalise_period(period),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "metric": metric,
            "group_by": group_by,
            "count": len(per_key),
            "items": items,
            "truncated": len(per_key) > limit,
            "days_in_window": (end - start).days + 1,
            "days_with_data": len({r.date for r in in_window}),
            "period_complete": end < data_end,
            "data_end": data_end.isoformat(),
        },
    }
