"""The live agent eval (ev-05): run each case through the real pipeline, score it, report.

    uv run python -m seller_pulse.evals.agent_eval [--case AE-03 ...] [--json] [--no-report]

Live, never a pytest test: it needs `GROQ_API_KEY` and the ingested store. The agent runs
through the same `chat.respond` the app uses — no parallel copy of the pipeline. Cases run
sequentially (Groq rate limits; 18 cases is small).

Per case: `respond` → `run_checks` + `check_groundedness` → `judge` → `resolve_dimensions`.
A case passes iff no dimension fails. The score is passed / scored cases against
`PASS_THRESHOLD`; known-gap cases run and are reported but don't count. Dimension and bucket
rates are diagnostic only.

Exit codes mirror `evals/retrieval_eval.py`: 0 at or above the threshold, 1 below, 2 the eval could not
run (no API key, empty store, malformed case file, unknown `--case`, the agent call raised).
A mid-run agent error is exit 2, not a failed case — an outage is not a score.
"""

import asyncio
import json
import statistics
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from fractions import Fraction
from functools import partial
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from seller_pulse.agent import ToolCallRecord
from seller_pulse.chat import Classifier, respond
from seller_pulse.config import PROJECT_ROOT, Settings, load_settings
from seller_pulse.evals.cases import AgentCase, load_cases
from seller_pulse.evals.checks import CheckResult, Dimension, Groundedness, check_groundedness, run_checks
from seller_pulse.evals.judge import Attempt, Verdict, judge
from seller_pulse.llm import get_router_client
from seller_pulse.llm.base import LLMClient
from seller_pulse.llm.groq_client import GroqLLMClient
from seller_pulse.rag.context import render_context
from seller_pulse.evals.retrieval_eval import HarnessError, check_store
from seller_pulse.rag.retrieval import Retriever, build_retriever
from seller_pulse.rag.store import get_client, policy_collection, review_collection
from seller_pulse.router import Route, classify_query
from seller_pulse.sanitize import sanitize
from seller_pulse.tools import build_tools

PASS_THRESHOLD = 0.8
TEMPERATURE = 0
REPORTS_DIR = PROJECT_ROOT / "evals" / "reports"
DIMENSIONS = tuple(Dimension)
_MARK = {"pass": "✓", "fail": "✗", "n/a": "–"}


@dataclass(frozen=True)
class Pipeline:
    client: LLMClient
    retriever: Retriever
    tools: list[BaseTool]
    classify: Classifier
    judge_model: BaseChatModel


@dataclass(frozen=True)
class CaseRun:
    case: AgentCase
    answer: str
    trace: list[ToolCallRecord]
    routes: frozenset[Route]
    route_fallback: bool
    retrieved_context: str
    checks: list[CheckResult]  # the case's checks, then the automatic groundedness check
    groundedness: Groundedness
    verdict: Verdict
    dimensions: dict[str, str]
    latency_ms: int

    @property
    def passed(self) -> bool:
        return "fail" not in self.dimensions.values()


def _suspect_key(value: str) -> str:
    """Suspects are bare numbers (`9.6`); tolerate the judge echoing them as `9.6%` or `$9.60`."""
    return value.strip().strip("$%").strip()


def _points_met(verdict: Verdict) -> dict[int, bool]:
    return {p.point: p.met for p in verdict.points}


def resolve_dimensions(
    checks: list[CheckResult], verdict: Verdict, suspects: Sequence[str] = (), must: Sequence[str] = ()
) -> dict[str, str]:
    """Each dimension → fail if anything contributing failed, pass if ≥1 applied, else n/a.

    `tool_use` is deterministic only. For `grounded`, a suspect the judge called `fabricated`,
    or didn't classify at all, is a fail — the judge can't pass its way around one. `behavior`
    is one result per `must` point, on the same rule: a point the judge didn't return is unmet.
    """
    results: dict[str, list[bool]] = {d: [] for d in DIMENSIONS}
    for check in checks:
        results[check.dimension].append(check.passed)
    for dimension in (Dimension.ACCURACY, Dimension.GROUNDED):
        dimension_verdict = getattr(verdict, dimension)
        if dimension_verdict.result != "n/a":
            results[dimension].append(dimension_verdict.result == "pass")
    met = _points_met(verdict)
    results[Dimension.BEHAVIOR] = [met.get(i, False) for i in range(1, len(must) + 1)]
    classified = {_suspect_key(s.value): s.classification for s in verdict.suspects}
    results[Dimension.GROUNDED] += [classified.get(_suspect_key(s)) == "derived" for s in suspects]

    def resolve(passes: list[bool]) -> str:
        if not passes:
            return "n/a"
        return "pass" if all(passes) else "fail"

    return {str(d): resolve(results[d]) for d in DIMENSIONS}


async def run_case(case: AgentCase, pipeline: Pipeline) -> CaseRun:
    started = time.perf_counter()
    result = await respond(
        case.message,
        None,
        client=pipeline.client,
        retriever=pipeline.retriever,
        tools=pipeline.tools,
        classify=pipeline.classify,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    # The same block `respond` put in the system prompt — retrieval is deterministic for a
    # fixed store. If that ever drifts, expose the context on `ChatResult` instead.
    retrieved_context = render_context(pipeline.retriever.retrieve(sanitize(case.message)))

    checks = run_checks(case.checks, result.text, result.trace)
    grounding = check_groundedness(
        result.text,
        trace=result.trace,
        retrieved_context=retrieved_context,
        query=case.query,
        query_context=case.query_context or "",
        allow=case.groundedness_allow,
    )
    checks.append(grounding.check)
    attempt = Attempt(
        answer=result.text, trace=result.trace, retrieved_context=retrieved_context, suspects=grounding.suspects
    )
    verdict = await judge(pipeline.judge_model, case.rubric, attempt)
    return CaseRun(
        case=case,
        answer=result.text,
        trace=result.trace,
        routes=result.routes,
        route_fallback=result.route_fallback,
        retrieved_context=retrieved_context,
        checks=checks,
        groundedness=grounding,
        verdict=verdict,
        dimensions=resolve_dimensions(checks, verdict, grounding.suspects, case.must),
        latency_ms=latency_ms,
    )


# --- summary


def _rate(passed: int, total: int) -> dict[str, Any]:
    return {"passed": passed, "total": total}


def summarize(runs: list[CaseRun]) -> dict[str, Any]:
    scored = [r for r in runs if r.case.scored]
    gaps = [r for r in runs if not r.case.scored]
    passed = sum(r.passed for r in scored)
    dimensions = {}
    for d in DIMENSIONS:
        applicable = [r for r in scored if r.dimensions[d] != "n/a"]
        dimensions[str(d)] = {
            "passed": sum(r.dimensions[d] == "pass" for r in applicable),
            "applicable": len(applicable),
        }
    buckets: dict[str, dict[str, int]] = {}
    for r in scored:
        bucket = buckets.setdefault(r.case.bucket, _rate(0, 0))
        bucket["total"] += 1
        bucket["passed"] += r.passed
    latencies = [r.latency_ms for r in runs]
    return {
        "score": {
            "passed": passed,
            "scored": len(scored),
            "rate": round(passed / len(scored), 3) if scored else None,
        },
        "known_gap": _rate(sum(r.passed for r in gaps), len(gaps)),
        "dimensions": dimensions,
        "buckets": buckets,
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "max": max(latencies, default=None),
        },
    }


def meets_threshold(passed: int, scored: int) -> bool:
    # Exact arithmetic: 12/15 sits exactly on the bar, with no float rounding either side of it.
    return scored == 0 or Fraction(passed, scored) >= Fraction(str(PASS_THRESHOLD))


# --- report


def case_to_json(run: CaseRun) -> dict[str, Any]:
    return {
        "id": run.case.id,
        "source_query": run.case.source_query,
        "bucket": run.case.bucket,
        "status": run.case.status,
        "passed": run.passed,
        "dimensions": run.dimensions,
        "query": run.case.message,
        "must": list(run.case.must),
        "routes": [r.value for r in sorted(run.routes)],
        "route_fallback": run.route_fallback,
        "answer": run.answer,
        "retrieved_context": run.retrieved_context,
        "trace": [asdict(r) for r in run.trace],
        "checks": [asdict(c) for c in run.checks],
        "groundedness": {"ungrounded_ids": run.groundedness.ungrounded_ids, "suspects": run.groundedness.suspects},
        "verdict": run.verdict.model_dump(),
        "latency_ms": run.latency_ms,
    }


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out.stdout.strip()


def build_report(runs: list[CaseRun], settings: Settings, run_at: datetime) -> dict[str, Any]:
    return {
        "run_at": run_at.isoformat(timespec="seconds"),
        "git_sha": _git("rev-parse", "--short", "HEAD") or "unknown",
        "dirty": bool(_git("status", "--porcelain")),
        "agent_model": settings.groq_model,
        "router_model": settings.router_model,
        "judge_model": settings.judge_model,
        "temperature": TEMPERATURE,
        "threshold": PASS_THRESHOLD,
        **summarize(runs),
        "cases": [case_to_json(r) for r in runs],
    }


def write_report(report: dict[str, Any], run_at: datetime, reports_dir: Path | None = None) -> Path:
    reports_dir = reports_dir or REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{run_at:%Y%m%dT%H%M%S}-{report['git_sha']}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# --- human log


def render(run: CaseRun) -> None:
    print(f"{run.case.id}  ({run.case.source_query}, {run.case.bucket}, {run.case.status})  "
          f"{'PASS' if run.passed else 'FAIL'}")
    print(f"query: {run.case.query}")
    print(f"routes: {[r.value for r in sorted(run.routes)]}" + ("  (fallback)" if run.route_fallback else ""))
    print("  " + "  ".join(f"{d} {_MARK[r]}" for d, r in run.dimensions.items()))
    for check in run.checks:
        if not check.passed:
            print(f"  ✗ {check.kind} [{check.dimension}]: {check.detail}")
    if run.verdict.judge_error:
        print(f"  judge error: {run.verdict.accuracy.reasons[0]}")
    for d in (Dimension.ACCURACY, Dimension.GROUNDED):
        if run.dimensions[d] == "fail":
            for missed in getattr(run.verdict, d).missed:
                print(f"  {d} missed: {missed}")
    if run.dimensions[Dimension.BEHAVIOR] == "fail":
        points = {p.point: p for p in run.verdict.points}
        for i, point in enumerate(run.case.must, start=1):
            p = points.get(i)
            if p is None or not p.met:
                print(f"  behavior unmet {i}. {point}" + (f" — {p.evidence}" if p else " — not graded"))
    if run.dimensions[Dimension.GROUNDED] == "fail":
        if run.groundedness.ungrounded_ids:
            print(f"  ungrounded IDs: {run.groundedness.ungrounded_ids}")
        classified = {_suspect_key(s.value): s for s in run.verdict.suspects}
        for suspect in run.groundedness.suspects:
            s = classified.get(_suspect_key(suspect))
            print(f"  suspect {suspect}: " + (f"{s.classification} — {s.basis}" if s else "not classified"))
    print()


def _seconds(ms: int | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f}s"


def render_footer(summary: dict[str, Any]) -> None:
    score, gap, latency = summary["score"], summary["known_gap"], summary["latency_ms"]
    rate = "n/a" if score["rate"] is None else f"{score['rate']:.1%}"
    print(f"{score['passed']}/{score['scored']} scored ({rate})  target ≥ {PASS_THRESHOLD:.0%}  "
          f"· known-gap {gap['passed']}/{gap['total']}")
    print(" · ".join(f"{d} {v['passed']}/{v['applicable']}" for d, v in summary["dimensions"].items()))
    buckets = " · ".join(f"{b} {v['passed']}/{v['total']}" for b, v in summary["buckets"].items())
    print(f"{buckets} · latency p50 {_seconds(latency['p50'])} max {_seconds(latency['max'])}")
    print(f"RESULT: {'PASS' if meets_threshold(score['passed'], score['scored']) else 'FAIL'}")


# --- setup + CLI


def build_pipeline(settings: Settings) -> Pipeline:
    chroma = get_client(settings.chroma_path)
    check_store(policy_collection(chroma).count(), review_collection(chroma).count())
    judge_client = GroqLLMClient(api_key=settings.groq_api_key, model=settings.judge_model, temperature=TEMPERATURE)
    return Pipeline(
        client=GroqLLMClient(api_key=settings.groq_api_key, model=settings.groq_model, temperature=TEMPERATURE),
        retriever=build_retriever(settings),
        tools=build_tools(settings),
        classify=partial(classify_query, get_router_client(settings).chat_model),
        judge_model=judge_client.chat_model,
    )


def _case_filter(argv: list[str]) -> list[str]:
    ids = []
    for i, arg in enumerate(argv):
        if arg == "--case":
            if i + 1 >= len(argv):
                raise HarnessError("--case needs a case id")
            ids.append(argv[i + 1])
    return ids


def select_cases(cases: list[AgentCase], ids: list[str]) -> list[AgentCase]:
    if not ids:
        return cases
    unknown = sorted(set(ids) - {c.id for c in cases})
    if unknown:
        raise HarnessError(f"unknown --case id(s): {unknown}")
    return [c for c in cases if c.id in ids]


def _fail(message: str, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps({"error": message}))
    else:
        print(f"ERROR: {message}")
    return 2


async def run_eval(cases: list[AgentCase], pipeline: Pipeline, *, json_mode: bool) -> list[CaseRun]:
    runs = []
    for case in cases:
        try:
            run = await run_case(case, pipeline)
        except Exception as exc:  # noqa: BLE001 - an agent/Groq error aborts the run (exit 2)
            raise HarnessError(f"{case.id}: agent call failed: {type(exc).__name__}: {exc}") from exc
        if json_mode:
            print(json.dumps(case_to_json(run), ensure_ascii=False), flush=True)
        else:
            render(run)
        runs.append(run)
    return runs


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    json_mode = "--json" in argv

    try:
        settings = load_settings()
        if not settings.groq_api_key:
            raise HarnessError("GROQ_API_KEY is not set — the agent eval calls Groq live")
        cases = select_cases(load_cases(), _case_filter(argv))
        pipeline = build_pipeline(settings)
    except Exception as exc:  # noqa: BLE001 - this boundary converts any setup failure to exit 2
        return _fail(f"could not run agent eval: {exc}", json_mode)

    run_at = datetime.now()
    if not json_mode:
        print("SellerPulse agent eval")
        print(f"agent: {settings.groq_model}   router: {settings.router_model}   "
              f"judge: {settings.judge_model}   temperature: {TEMPERATURE}")
        print(f"cases: {len(cases)}   run: {run_at.isoformat(timespec='seconds')}")
        print()
        print("─" * 66)

    try:
        runs = asyncio.run(run_eval(cases, pipeline, json_mode=json_mode))
    except HarnessError as exc:
        return _fail(f"agent eval aborted: {exc}", json_mode)

    summary = summarize(runs)
    if not json_mode:
        print("─" * 66)
        render_footer(summary)
    if "--no-report" not in argv:
        path = write_report(build_report(runs, settings, run_at), run_at)
        if not json_mode:
            print(f"report: {path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path}")

    return 0 if meets_threshold(summary["score"]["passed"], summary["score"]["scored"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
