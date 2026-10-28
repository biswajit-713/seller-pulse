"""Deterministic answer text for single-tool analytics turns.

The model words the same figures differently on every ask (a list one time, a sentence the
next), so when a turn is nothing but one successful analytics call the answer is rendered here
from the tool's result envelope instead. The model's own reply is discarded for those turns;
everything else (several tool calls, a failure, `find_listing`, memory, reviews, policy) keeps
the model's text, steered by the prompt's format rules.

Every number printed comes straight from the result — or is the percentage change between two of
its figures — so `guardrails.check_output` still passes. When the two sales windows have
different data coverage no percentage is printed: a per-day average is not in the result, and
the guardrail would flag it.
"""

import logging
import re
from collections.abc import Callable, Iterable

from seller_pulse.agent import ToolCallRecord
from seller_pulse.memory import Preference

logger = logging.getLogger(__name__)

_KEYWORD_PERIOD = re.compile(r"[a-z0-9_]+")


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _span(start: str, end: str) -> str:
    return start if start == end else f"{start} to {end}"


def _window(data: dict) -> str:
    """`last 30 days (2026-08-28 to 2026-09-26)`; a literal date or range is just its span."""
    span = _span(data["start"], data["end"])
    period = data["period"]
    if _KEYWORD_PERIOD.fullmatch(period):
        return f"{period.replace('_', ' ')} ({span})"
    return span


def _coverage_note(data: dict) -> str | None:
    parts = []
    if data["days_with_data"] < data["days_in_window"]:
        parts.append(f"data covers {data['days_with_data']} of {data['days_in_window']} days")
    if not data["period_complete"]:
        parts.append(f"the period is partial (data through {data['data_end']})")
    if not parts:
        return None
    return f"Note: {'; '.join(parts)}."


def _join(*blocks: str | None) -> str:
    return "\n\n".join(block for block in blocks if block)


def _top_products(data: dict, _preferences: list[Preference]) -> str:
    items = data["items"]
    lines = [
        f"{i}. {item['sku']} — {item['title']}: {item['units_sold']} units, "
        f"{_money(item['revenue_usd'])}"
        for i, item in enumerate(items, 1)
    ]
    shown = (
        f"Showing the top results only; {data['count']} products had sales in this window."
        if data["truncated"]
        else None
    )
    return _join(
        f"**Top products by {data['metric']}, {_window(data)}**",
        "\n".join(lines),
        shown,
        _coverage_note(data),
    )


def _change(current: float, previous: float) -> str:
    if previous == 0:
        return "no change figure (previous was 0)"
    pct = round((current - previous) / previous * 100, 1)
    if pct == 0:
        return "unchanged"
    return f"{'up' if pct > 0 else 'down'} {abs(pct)}%"


def _comparison(data: dict) -> str:
    previous = data["previous"]
    if previous is None:
        return "No earlier window to compare with."
    head = f"Compared with {_span(previous['start'], previous['end'])}:"
    if previous["days_with_data"] != data["days_with_data"]:
        return (
            f"{head} revenue was {_money(previous['revenue_usd'])} and {previous['units_sold']:,} "
            f"units, but with {previous['days_with_data']} of {previous['days_in_window']} days "
            f"of data against {data['days_with_data']} of {data['days_in_window']} now, so it "
            "isn't a like-for-like comparison."
        )
    return (
        f"{head} revenue {_change(data['revenue_usd'], previous['revenue_usd'])} "
        f"({_money(previous['revenue_usd'])}), units "
        f"{_change(data['units_sold'], previous['units_sold'])} ({previous['units_sold']:,})."
    )


def _sales(data: dict, _preferences: list[Preference]) -> str:
    scope = f"Sales for {data['sku']}" if data.get("sku") else "Sales"
    figures = "\n".join(
        [
            f"- Revenue: {_money(data['revenue_usd'])}",
            f"- Units sold: {data['units_sold']:,}",
            f"- Order lines: {data['order_lines']:,}",
        ]
    )
    return _join(
        f"**{scope}, {_window(data)}**", figures, _comparison(data), _coverage_note(data)
    )


def _listing_line(item: dict) -> str:
    line = f"- {item['sku']} — {item['title']}: {item['stock_qty']} in stock ({item['status']})"
    if _active_without_stock(item):
        line += ". Active with no stock — fix the listing"
    return line


def _active_without_stock(item: dict) -> bool:
    return item["stock_qty"] == 0 and item["status"] == "Active"


def _low_stock(data: dict, _preferences: list[Preference]) -> str:
    threshold = data["threshold"]
    if not data["items"]:
        return f"No listings are at or below {threshold} units."
    shown = (
        f"{data['count']} listings match; showing the lowest only."
        if data["truncated"]
        else None
    )
    return _join(
        f"**Low stock, at or below {threshold} units**",
        "\n".join(_listing_line(item) for item in data["items"]),
        shown,
    )


def _restock_threshold(preferences: Iterable[Preference]) -> int | None:
    for pref in preferences:
        if pref.key == "restock_threshold" and (match := re.search(r"\d+", pref.value)):
            return int(match.group())
    return None


def _inventory(data: dict, preferences: list[Preference]) -> str:
    notes = []
    if _active_without_stock(data):
        notes.append("This listing is Active with no stock — an inconsistency to fix.")
    threshold = _restock_threshold(preferences)
    if threshold is not None and data["stock_qty"] <= threshold:
        notes.append(f"At or below your restock threshold ({threshold}): time to restock.")
    return _join(
        f"**{data['sku']} — {data['title']}**",
        "\n".join(
            [
                f"- Stock: {data['stock_qty']}",
                f"- Status: {data['status']}",
                f"- Price: {_money(data['price_usd'])}",
            ]
        ),
        "\n".join(notes),
    )


_FORMATTERS: dict[str, Callable[[dict, list[Preference]], str]] = {
    "get_top_products": _top_products,
    "get_sales_analytics": _sales,
    "list_low_stock": _low_stock,
    "check_inventory_status": _inventory,
}


def render_answer(trace: list[ToolCallRecord], preferences: list[Preference]) -> str | None:
    """The deterministic answer for a turn that made exactly one successful, formattable tool
    call; `None` for any other turn, so the caller keeps the model's text."""
    if len(trace) != 1:
        return None
    record = trace[0]
    formatter = _FORMATTERS.get(record.name)
    if formatter is None or not record.result.get("ok"):
        return None
    try:
        return formatter(record.result["data"], preferences)
    except (KeyError, TypeError):
        # A result missing a field this renderer expects: the model's text is the safer answer.
        logger.warning("could not render %s result; keeping the model's text", record.name)
        return None
