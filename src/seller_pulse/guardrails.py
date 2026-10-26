"""Output guardrails — a post-generation check of the model's final answer (docs/guardrails.md).

`check_output` reports what the answer does against this turn's sources: ids and numbers no
source carries (G1), a draft awaiting approval or a claim that something was posted (G2), and a
grounded policy refusal (G3). `annotate` appends caution lines for the first two; it never
blocks or rewrites the answer.

The tokeniser here is shared with the agent eval (`evals/checks.py`), so the runtime check and
the eval can never disagree about what counts as grounded.

Numbers are compared as canonical tokens, not substrings: `$41,904.71`, `41904.71` and
`41,904.71` are one token, and `904` never matches inside `9045` or `41904.71`. ID digits and
list markers (`1. `) are not numbers.
"""

import json
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from itertools import permutations

from seller_pulse.agent import ToolCallRecord
from seller_pulse.memory import Preference
from seller_pulse.prompts import DATA_END, DATA_START, DRAFT_LABEL, TODAY
from seller_pulse.router import Route

ID_RE = re.compile(r"\b(?:SKU-\d{4}|REV-\d+|pol-\w+)\b", re.IGNORECASE)
LIST_MARKER_RE = re.compile(r"^[ \t]*\d+[.)][ \t]", re.MULTILINE)
# Models emit U+2010/U+2011 (hyphen, non-breaking hyphen) inside dates and IDs — `2026‑09‑14`,
# `SKU‑1001`. Unnormalised, a date splits into three numeric suspects and an ID escapes the ID
# check entirely, so answer and sources are both folded to ASCII `-` before anything is matched.
HYPHENS = str.maketrans({"‐": "-", "‑": "-"})
PERCENT_RE = re.compile(r"\s?%")  # `9.5%` and the spaced `9.5 %` models also emit
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

    A number followed by `%` (optionally one space between) is sourced when it is the percentage change between two
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
        if PERCENT_RE.match(answer, m.end()):
            if derived is None:
                derived = _derived_percents(source_numbers)
            if token in derived:
                continue
        unsourced.append(m.group())
    return ungrounded_ids, list(dict.fromkeys(unsourced))


def turn_sources(trace: Iterable[ToolCallRecord], retrieved_context: str, query: str) -> list[str]:
    """What an answer may draw figures and ids from: this turn's tool calls, retrieved context,
    the seller's own query and the dates the system prompt states — nothing else from the prompt,
    so its example wording can't launder a fabricated figure."""
    sources = [json.dumps({"args": r.args, "result": r.result}) for r in trace]
    return [*sources, retrieved_context, query, TODAY, DATA_START, DATA_END]


# Models write `I’ve` as often as `I've`; folded before the apostrophe-bearing patterns run.
APOSTROPHES = str.maketrans({"’": "'"})
PUBLISH_CLAIM_RE = re.compile(
    r"\b(?:I(?:'ve| have)|(?:has|have) been|was|were)\s+(?:posted|published|sent)\b", re.IGNORECASE
)
# A bare leading "No" ("No.", "No, …", "No — …") refuses too; "No problem" doesn't.
REFUSAL_RE = re.compile(
    r"\b(?:can't|cannot|won't|will not|not allowed|isn't allowed|decline)|^no(?=\s*[.,!;:—–-]|$)", re.IGNORECASE
)
FIRST_SENTENCE_RE = re.compile(r"(?<=[.!?])\s|\n")

UNVERIFIED_NOTE = (
    "⚠ Guardrail: couldn't verify {items} against this turn's tool results or retrieved data — "
    "treat as unverified."
)
PUBLISH_NOTE = "⚠ Guardrail: nothing has been posted or sent — drafts wait for your approval."


@dataclass(frozen=True)
class GuardrailReport:
    unverified_figures: list[str]
    ungrounded_ids: list[str]
    draft_pending: bool
    publish_claim: bool
    policy_refusal: bool
    policy_clauses: list[str]

    @property
    def triggered(self) -> bool:
        return any(
            (
                self.unverified_figures,
                self.ungrounded_ids,
                self.draft_pending,
                self.publish_claim,
                self.policy_refusal,
                self.policy_clauses,
            )
        )


def check_output(
    answer: str,
    *,
    trace: list[ToolCallRecord],
    retrieved_context: str,
    query: str,
    preferences: list[Preference],
    routes: Collection[Route],
) -> GuardrailReport:
    # A saved preference (a restock_threshold of 5) may be stated back to the seller.
    sources = turn_sources(trace, retrieved_context, query) + [p.value for p in preferences]
    ungrounded_ids, unverified_figures = find_ungrounded(answer, sources)

    folded = answer.translate(HYPHENS).translate(APOSTROPHES)
    retrieved = {m.lower() for m in ID_RE.findall(retrieved_context.translate(HYPHENS))}
    cited = (m.lower() for m in ID_RE.findall(folded))
    policy_clauses = list(dict.fromkeys(m for m in cited if m.startswith("pol-") and m in retrieved))
    first_sentence = FIRST_SENTENCE_RE.split(folded.strip(), maxsplit=1)[0]
    policy_refusal = Route.POLICY in routes and bool(policy_clauses) and bool(REFUSAL_RE.search(first_sentence))

    return GuardrailReport(
        unverified_figures=unverified_figures,
        ungrounded_ids=ungrounded_ids,
        draft_pending=DRAFT_LABEL in answer,
        publish_claim=bool(PUBLISH_CLAIM_RE.search(folded)),
        policy_refusal=policy_refusal,
        policy_clauses=policy_clauses,
    )


def annotate(answer: str, report: GuardrailReport) -> str:
    """``answer`` with a caution line per G1/G2 finding; draft and refusal are status only."""
    notes = []
    if unverified := report.ungrounded_ids + report.unverified_figures:
        notes.append(UNVERIFIED_NOTE.format(items=", ".join(unverified)))
    if report.publish_claim:
        notes.append(PUBLISH_NOTE)
    return "\n\n".join([answer, *notes]) if notes else answer
