"""The LLM judge (ev-04): grades one answer on accuracy, groundedness and behaviour.

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


class Verdict(BaseModel):
    suspects: list[SuspectVerdict]
    accuracy: DimensionVerdict
    grounded: DimensionVerdict
    behavior: DimensionVerdict
    judge_error: bool = False


@dataclass(frozen=True)
class Rubric:
    query: str
    query_context: str | None
    expected_behavior: str
    expected_answer: str
    notes: str | None


@dataclass(frozen=True)
class Attempt:
    answer: str
    trace: list[ToolCallRecord]
    retrieved_context: str
    suspects: list[str]  # from check_groundedness


JUDGE_PROMPT = """\
You grade one answer from Seller Pulse, an assistant for a solo marketplace seller. Grade three \
dimensions independently and return the structured verdict.

## accuracy — graded against the REFERENCE
Are the facts the answer states consistent with the reference answer, allowing the accepted \
alternates in NOTES? Wording need not match. Missing a headline fact the reference has → fail. \
`n/a` only when the reference carries no checkable facts (e.g. a pure refusal with no figures).

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

## behavior — graded against the RUBRIC
Does the answer do each thing the rubric asks (refusal + reason + alternative, draft label, \
caveat, stated window, …)? List each unmet point in `missed`. Never `n/a`.

On every dimension: don't penalise extra correct detail or style. Put one reason per rubric \
point or claim in `reasons`; `missed` is empty on a pass.
"""


def _section(title: str, body: str) -> str:
    return f"### {title}\n{body.strip() or '(none)'}"


def _render_trace(trace: list[ToolCallRecord]) -> str:
    calls = [json.dumps({"name": r.name, "args": r.args, "result": r.result}) for r in trace]
    return "\n".join(calls) or "(no tool calls)"


def _render_suspects(suspects: list[str]) -> str:
    if not suspects:
        return "(none — every number in the answer matched a source; return an empty suspects list)"
    return "\n".join(f"- {s}" for s in suspects)


def build_messages(rubric: Rubric, attempt: Attempt) -> list:
    materials = "\n\n".join([
        "## Case",
        _section("QUERY", rubric.query),
        _section("PASTED QUERY CONTEXT", rubric.query_context or ""),
        _section("RUBRIC (expected behavior)", rubric.expected_behavior),
        _section("REFERENCE (expected answer — content must be consistent with; wording need not match)",
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
    return Verdict(suspects=[], accuracy=failed, grounded=failed, behavior=failed, judge_error=True)


async def judge(model: BaseChatModel, rubric: Rubric, attempt: Attempt) -> Verdict:
    try:
        verdict = await model.with_structured_output(Verdict).ainvoke(build_messages(rubric, attempt))
    except Exception as exc:
        return _error_verdict(f"{type(exc).__name__}: {exc}")
    if not isinstance(verdict, Verdict):
        return _error_verdict(f"unparseable output: {verdict!r}")
    return verdict
