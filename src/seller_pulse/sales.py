"""The sales domain.

`resolve_period` turns the `period` grammar from `docs/tools.md` §3 into an inclusive
`(start, end)` date pair, so aggregation never has to think about calendars. It is pure: no
CSV access, and `today` is a parameter rather than `date.today()` — the dataset is frozen, so
callers pass `date.fromisoformat(prompts.TODAY)`.
"""

from datetime import date, timedelta


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


def resolve_period(period: str, today: date) -> tuple[date, date]:
    """Resolve `period` to an inclusive `(start, end)` window, or raise `PeriodError`.

    Keywords are normalised (trimmed, lower-cased, spaces/hyphens → underscores) so
    `"last week"` works. Dates are matched before that normalisation, since it would mangle
    the hyphens in `YYYY-MM-DD`.
    """
    text = period.strip().lower()
    if not text:
        raise _invalid("Period is empty.")

    if text[0].isdigit():
        if ".." in text:
            start_text, _, end_text = text.partition("..")
            start, end = _parse_date(start_text), _parse_date(end_text)
        else:
            start = end = _parse_date(text)
    else:
        keyword = text.replace(" ", "_").replace("-", "_")
        window = _keyword_window(keyword, today)
        if window is None:
            raise _invalid(f"Unknown period '{period.strip()}'.")
        start, end = window

    if start > end:
        raise _invalid(f"Start {start} is after end {end}.")
    if end > today:
        raise _invalid(f"End {end} is after today ({today}); there is no future data.")
    return start, end
