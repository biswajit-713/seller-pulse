"""Deterministic scorers for the agent eval — no model involved.

`run_checks` scores a case's hand-written checks (`agent_cases.jsonl`, ev-01) against the
answer text and the tool trace. `check_groundedness` is the automatic grounding check that runs on
every case: an ID in the answer that no source carries is fabricated (IDs can't be derived), so
it fails outright; a number no source carries may still be derived ("9.6%", a difference), so it
only becomes a *suspect* for the judge (ev-04) to classify.

Numbers are compared as canonical tokens, not substrings: `$41,904.71`, `41904.71` and
`41,904.71` are one token, and `904` never matches inside `9045` or `41904.71`. The system
prompt is deliberately *not* a source beyond the dates it states (`TODAY`, `DATA_START`,
`DATA_END`) — otherwise a number from its example wording could launder a fabricated figure.

Malformed checks (unknown kind, `behavior` or an unknown dimension) raise `ValueError`; the
runner maps that to exit 2, a malformed case file.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from seller_pulse.agent import ToolCallRecord
from seller_pulse.prompts import DATA_END, DATA_START, TODAY


class Dimension(StrEnum):
    TOOL_USE = "tool_use"
    ACCURACY = "accuracy"
    GROUNDED = "grounded"
    BEHAVIOR = "behavior"  # judge-only


class CheckKind(StrEnum):
    TOOL_CALLED = "tool_called"
    NO_TOOL_CALLED = "no_tool_called"
    CONTAINS_ALL = "contains_all"
    CONTAINS_ANY = "contains_any"
    NOT_CONTAINS_PATTERN = "not_contains_pattern"
    GROUNDEDNESS = "groundedness"  # automatic on every case, never written in the case file


DEFAULT_DIMENSIONS = {
    CheckKind.TOOL_CALLED: Dimension.TOOL_USE,
    CheckKind.NO_TOOL_CALLED: Dimension.TOOL_USE,
    CheckKind.CONTAINS_ALL: Dimension.ACCURACY,
    CheckKind.CONTAINS_ANY: Dimension.ACCURACY,
    CheckKind.NOT_CONTAINS_PATTERN: Dimension.GROUNDED,
}
CHECK_DIMENSIONS = frozenset(Dimension) - {Dimension.BEHAVIOR}

_ID_RE = re.compile(r"\b(?:SKU-\d{4}|REV-\d+|pol-\w+)\b", re.IGNORECASE)
_LIST_MARKER_RE = re.compile(r"^[ \t]*\d+[.)][ \t]", re.MULTILINE)
# Models emit U+2010/U+2011 (hyphen, non-breaking hyphen) inside dates and IDs — `2026‑09‑14`,
# `SKU‑1001`. Unnormalised, a date splits into three numeric suspects and an ID escapes the ID
# check entirely, so answer and sources are both folded to ASCII `-` before anything is matched.
_HYPHENS = str.maketrans({"\u2010": "-", "\u2011": "-"})
_NUMBER_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


@dataclass(frozen=True)
class CheckResult:
    kind: CheckKind
    dimension: Dimension  # never BEHAVIOR — that is judge-only
    passed: bool
    detail: str  # human-readable why


@dataclass(frozen=True)
class Groundedness:
    check: CheckResult  # kind="groundedness", dimension="grounded"; fails iff ungrounded_ids
    ungrounded_ids: list[str]
    suspects: list[str]  # numbers in the answer with no source match — for the judge


def _canonical(token: str) -> str:
    """`41,904.70` → `41904.7`; `1,000.00` → `1000`. ISO dates pass through unchanged."""
    if token.count("-") == 2:
        return token
    token = token.replace(",", "")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token


def _number_tokens(text: str) -> list[tuple[str, str]]:
    """(surface, canonical) for each number in ``text``, skipping ID digits and list markers."""
    text = _ID_RE.sub(" ", text)
    text = _LIST_MARKER_RE.sub(" ", text)
    return [(m.group(), _canonical(m.group())) for m in _NUMBER_RE.finditer(text)]


def _is_numeric(needle: str) -> bool:
    return _NUMBER_RE.fullmatch(needle.strip().lstrip("$")) is not None


def _contains(answer: str, answer_numbers: set[str], needle: str) -> bool:
    if _is_numeric(needle):
        return _canonical(needle.strip().lstrip("$")) in answer_numbers
    return needle.lower() in answer.lower()


def _accepted(value: object) -> list:
    return value if isinstance(value, list) else [value]


def _norm_arg(value: object) -> str:
    return str(value).strip().lower()


def _kind_and_dimension(check: dict) -> tuple[CheckKind, Dimension]:
    kind = check.get("kind")
    if kind not in DEFAULT_DIMENSIONS:  # also rejects `groundedness` written in the file
        raise ValueError(f"Unknown check kind {kind!r}: {check}")
    dimension = check.get("dimension", DEFAULT_DIMENSIONS[kind])
    if dimension not in CHECK_DIMENSIONS:
        raise ValueError(f"Check dimension {dimension!r} not allowed (behavior is judge-only): {check}")
    return CheckKind(kind), Dimension(dimension)


def _tool_called(check: dict, trace: list[ToolCallRecord]) -> tuple[bool, str]:
    name = check["name"]
    calls = [r for r in trace if r.name == name]
    if not calls:
        return False, f"{name} never called"
    wanted = check.get("args") or {}
    for call in calls:
        if all(
            _norm_arg(call.args.get(arg)) in {_norm_arg(v) for v in _accepted(values)}
            for arg, values in wanted.items()
        ):
            return True, f"{name} called with {call.args}"
    seen = [c.args for c in calls]
    return False, f"{name} called, but no call matched {wanted}; saw {seen}"


def _no_tool_called(check: dict, trace: list[ToolCallRecord]) -> tuple[bool, str]:
    name = check.get("name")
    hits = [r.name for r in trace if name is None or r.name == name]
    if hits:
        return False, f"unexpected call(s): {hits}"
    return True, f"{name or 'no tool'} not called"


def _contains_all(check: dict, answer: str, numbers: set[str]) -> tuple[bool, str]:
    missing = [n for n in check["needles"] if not _contains(answer, numbers, n)]
    if missing:
        return False, f"missing {missing}"
    return True, f"all of {check['needles']} present"


def _contains_any(check: dict, answer: str, numbers: set[str]) -> tuple[bool, str]:
    for group in check["groups"]:
        if all(_contains(answer, numbers, n) for n in group):
            return True, f"group {group} present"
    return False, f"no group fully present: {check['groups']}"


def _not_contains_pattern(check: dict, answer: str) -> tuple[bool, str]:
    match = re.search(check["pattern"], answer)
    if match:
        return False, f"forbidden pattern matched {match.group()!r}"
    return True, "forbidden pattern absent"


def run_checks(checks: list[dict], answer: str, trace: list[ToolCallRecord]) -> list[CheckResult]:
    answer = answer.translate(_HYPHENS)
    numbers = {canonical for _, canonical in _number_tokens(answer)}
    results = []
    for check in checks:
        kind, dimension = _kind_and_dimension(check)
        if kind is CheckKind.TOOL_CALLED:
            passed, detail = _tool_called(check, trace)
        elif kind is CheckKind.NO_TOOL_CALLED:
            passed, detail = _no_tool_called(check, trace)
        elif kind is CheckKind.CONTAINS_ALL:
            passed, detail = _contains_all(check, answer, numbers)
        elif kind is CheckKind.CONTAINS_ANY:
            passed, detail = _contains_any(check, answer, numbers)
        else:
            passed, detail = _not_contains_pattern(check, answer)
        results.append(CheckResult(kind=kind, dimension=dimension, passed=passed, detail=detail))
    return results


def check_groundedness(
    answer: str,
    *,
    trace: list[ToolCallRecord],
    retrieved_context: str,
    query: str,
    query_context: str = "",
    allow: Iterable[str] = (),
) -> Groundedness:
    sources = [json.dumps({"args": r.args, "result": r.result}) for r in trace]
    sources += [retrieved_context, query, query_context, TODAY, DATA_START, DATA_END, *allow]
    source_text = "\n".join(sources).translate(_HYPHENS)
    answer = answer.translate(_HYPHENS)

    source_ids = {m.upper() for m in _ID_RE.findall(source_text)}
    ungrounded_ids = list(dict.fromkeys(m for m in _ID_RE.findall(answer) if m.upper() not in source_ids))

    source_numbers = {canonical for _, canonical in _number_tokens(source_text)}
    suspects = list(
        dict.fromkeys(surface for surface, canonical in _number_tokens(answer) if canonical not in source_numbers)
    )

    if ungrounded_ids:
        detail = f"IDs not in any source: {ungrounded_ids}"
    else:
        detail = "every ID traced" + (f"; {len(suspects)} numeric suspect(s) for the judge" if suspects else "")
    check = CheckResult(
        kind=CheckKind.GROUNDEDNESS, dimension=Dimension.GROUNDED, passed=not ungrounded_ids, detail=detail
    )
    return Groundedness(check=check, ungrounded_ids=ungrounded_ids, suspects=suspects)
