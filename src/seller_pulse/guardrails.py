"""Output guardrails — which ids and numbers in an answer does no source carry?

The tokeniser here is shared with the agent eval (`evals/checks.py`), so the runtime check and
the eval can never disagree about what counts as grounded.

Numbers are compared as canonical tokens, not substrings: `$41,904.71`, `41904.71` and
`41,904.71` are one token, and `904` never matches inside `9045` or `41904.71`. ID digits and
list markers (`1. `) are not numbers.
"""

import re
from collections.abc import Iterable
from itertools import permutations

ID_RE = re.compile(r"\b(?:SKU-\d{4}|REV-\d+|pol-\w+)\b", re.IGNORECASE)
LIST_MARKER_RE = re.compile(r"^[ \t]*\d+[.)][ \t]", re.MULTILINE)
# Models emit U+2010/U+2011 (hyphen, non-breaking hyphen) inside dates and IDs — `2026‑09‑14`,
# `SKU‑1001`. Unnormalised, a date splits into three numeric suspects and an ID escapes the ID
# check entirely, so answer and sources are both folded to ASCII `-` before anything is matched.
HYPHENS = str.maketrans({"‐": "-", "‑": "-"})
NUMBER_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def canonical(token: str) -> str:
    """`41,904.70` → `41904.7`; `1,000.00` → `1000`. ISO dates pass through unchanged."""
    if _is_date(token):
        return token
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _is_date(token: str) -> bool:
    return token.count("-") == 2


def _blank(match: re.Match) -> str:
    return " " * len(match.group())  # keeps offsets, so a following `%` stays adjacent


def _number_matches(text: str) -> list[re.Match]:
    text = ID_RE.sub(_blank, text)
    text = LIST_MARKER_RE.sub(_blank, text)
    return list(NUMBER_RE.finditer(text))


def number_tokens(text: str) -> list[tuple[str, str]]:
    """(surface, canonical) for each number in ``text``, skipping ID digits and list markers."""
    return [(m.group(), canonical(m.group())) for m in _number_matches(text)]


def _derived_percents(numbers: set[str]) -> set[str]:
    """Canonical `round((a - b) / b * 100, 1)` (and its absolute value) over source number pairs."""
    values = {float(n) for n in numbers if not _is_date(n)} - {0.0}
    derived = set()
    for a, b in permutations(values, 2):
        change = round((a - b) / b * 100, 1)
        derived |= {canonical(str(change)), canonical(str(abs(change)))}
    return derived


def find_ungrounded(answer: str, sources: Iterable[str]) -> tuple[list[str], list[str]]:
    """(ungrounded ids, unsourced number surfaces) in ``answer``, deduped in answer order.

    A number directly followed by `%` is sourced when it is the percentage change between two
    source numbers — "up 8.2%" from 4210.5 and 3890.
    """
    source_text = "\n".join(sources).translate(HYPHENS)
    answer = answer.translate(HYPHENS)

    source_ids = {m.upper() for m in ID_RE.findall(source_text)}
    ungrounded_ids = list(dict.fromkeys(m for m in ID_RE.findall(answer) if m.upper() not in source_ids))

    source_numbers = {c for _, c in number_tokens(source_text)}
    derived: set[str] | None = None  # computed only if an unsourced `%` turns up
    unsourced = []
    for m in _number_matches(answer):
        token = canonical(m.group())
        if token in source_numbers:
            continue
        if answer[m.end() : m.end() + 1] == "%":
            if derived is None:
                derived = _derived_percents(source_numbers)
            if token in derived:
                continue
        unsourced.append(m.group())
    return ungrounded_ids, list(dict.fromkeys(unsourced))
