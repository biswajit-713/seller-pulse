"""The LLM judge (ev-04): grades one answer on accuracy, groundedness and behaviour.

Each dimension has one job, so a single miss never fails two of them. `behavior` is a yes/no
per point of the case's `must` list — the only place completeness is graded; the runner, not
the judge, folds the points into a dimension result. `accuracy` fails only on a *contradiction*
of the reference answer, never an omission: references are full exemplar answers, and grading
them as a checklist made every optional detail mandatory.

Inputs split in two: `Rubric` is what the answer is graded *against* (fixed per case), `Attempt`
is what one run produced and saw. `grounded` is judged only against `Attempt` — a correct claim
the agent had no source for still fails. No `tool_use` dimension: that one is deterministic only.

IDs and exact-match numbers are already settled by `check_groundedness`; the judge classifies
the leftover numeric suspects and grades non-numeric claims. The runner (ev-05), not the judge,
fails `grounded` on a `fabricated` or missing suspect.

`Verdict` is the only thing the runner reads, so a framework can replace this module later. A
judge error never raises — it comes back as an all-`fail` verdict with `judge_error=True`.
"""

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from seller_pulse.agent import ToolCallRecord


class DimensionVerdict(BaseModel):
    result: Literal["pass", "fail", "n/a"]
    reasons: list[str]  # each tied to a rubric point / claim
    missed: list[str]  # rubric points not met, or claims not traceable


class SuspectVerdict(BaseModel):
    value: str  # exactly as in the suspect list
    classification: Literal["derived", "fabricated"]
    basis: str  # e.g. "(1000-904)/1000 from trace" / "no source"


class PointVerdict(BaseModel):
    point: int  # 1-based number of the MUST point, as listed
    met: bool
    evidence: str  # the answer text that meets it, or what is missing


class Verdict(BaseModel):
    suspects: list[SuspectVerdict]
    points: list[PointVerdict]  # one per MUST point → `behavior`
    accuracy: DimensionVerdict  # contradictions of the reference only
    grounded: DimensionVerdict
    judge_error: bool = False


@dataclass(frozen=True)
class Rubric:
    query: str
    query_context: str | None
    must: tuple[str, ...]
    expected_answer: str
    notes: str | None


@dataclass(frozen=True)
class Attempt:
    answer: str
    trace: list[ToolCallRecord]
    retrieved_context: str
    suspects: list[str]  # from check_groundedness


JUDGE_PROMPT = """\
You grade one answer from Seller Pulse, an assistant for a solo marketplace seller. Grade each \
part independently and return the structured verdict. Each part has one job: never fail one \
part for something another part covers.

## points — graded against the MUST list
For every numbered MUST point, return one entry: `point` (its number), `met` (true/false) and \
`evidence` (the answer text that meets it, or what is missing). Judge each point on its own \
words, literally — the MUST list is the complete set of requirements; nothing else in the \
REFERENCE or NOTES is required. Wording need not match. A point that starts with "If" is met \
when its condition doesn't apply.

## accuracy — contradictions of the REFERENCE only
Fail only when the answer states a fact (a figure, ID, date, rating, tier, penalty, or what a \
policy says) that conflicts with the reference answer, allowing the accepted alternates in \
NOTES. Omissions never fail accuracy — the reference is one full example answer, not a \
checklist; completeness is graded by the MUST points alone. List each contradiction in \
`missed`. `n/a` when the answer states no fact the reference covers.

## grounded — graded against WHAT THE AGENT SAW (tool trace + retrieved context + query), \
never the reference
IDs and numbers that appear verbatim in a source are already verified; do not re-check them. \
Do exactly two things:
1. Classify every number in SUSPECTS as `derived` (a correct calculation or rounding of sourced \
figures — state the arithmetic and its source in `basis`) or `fabricated` (`basis`: why). Return \
one entry per suspect, `value` copied exactly as listed. Do not hunt for other numbers.
2. Grade the non-numeric factual claims (what a policy requires, what reviews say, what caused \
something) against the tool trace and retrieved context. A claim that is true but that nothing \
the agent saw supports is still a fail.
`n/a` when there are no suspects and no non-numeric factual claims.

On every part: don't penalise extra correct detail or style. Put one reason per claim in \
`reasons`; `missed` is empty on a pass.
"""


def _section(title: str, body: str) -> str:
    return f"### {title}\n{body.strip() or '(none)'}"


def _render_trace(trace: list[ToolCallRecord]) -> str:
    calls = [json.dumps({"name": r.name, "args": r.args, "result": r.result}) for r in trace]
    return "\n".join(calls) or "(no tool calls)"


def _render_must(must: tuple[str, ...]) -> str:
    return "\n".join(f"{i}. {point}" for i, point in enumerate(must, start=1))


def _render_suspects(suspects: list[str]) -> str:
    if not suspects:
        return "(none — every number in the answer matched a source; return an empty suspects list)"
    return "\n".join(f"- {s}" for s in suspects)


def build_messages(rubric: Rubric, attempt: Attempt) -> list:
    materials = "\n\n".join([
        "## Case",
        _section("QUERY", rubric.query),
        _section("PASTED QUERY CONTEXT", rubric.query_context or ""),
        _section("MUST (the complete requirements — one points entry each)", _render_must(rubric.must)),
        _section("REFERENCE (one full example answer — check for contradictions, not omissions)",
                 rubric.expected_answer),
        _section("NOTES (accepted alternates)", rubric.notes or ""),
        "## What the agent saw",
        _section("RETRIEVED CONTEXT", attempt.retrieved_context),
        _section("TOOL TRACE (one call per line)", _render_trace(attempt.trace)),
        "## What the agent said",
        _section("ANSWER", attempt.answer),
        _section("SUSPECTS (numbers with no exact source match)", _render_suspects(attempt.suspects)),
    ])
    return [SystemMessage(content=JUDGE_PROMPT), HumanMessage(content=materials)]


def _error_verdict(message: str) -> Verdict:
    failed = DimensionVerdict(result="fail", reasons=[f"judge error: {message}"], missed=[])
    return Verdict(suspects=[], points=[], accuracy=failed, grounded=failed, judge_error=True)


async def judge(model: BaseChatModel, rubric: Rubric, attempt: Attempt) -> Verdict:
    try:
        verdict = await model.with_structured_output(Verdict).ainvoke(build_messages(rubric, attempt))
    except Exception as exc:
        return _error_verdict(f"{type(exc).__name__}: {exc}")
    if not isinstance(verdict, Verdict):
        return _error_verdict(f"unparseable output: {verdict!r}")
    return verdict
