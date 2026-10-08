"""The route eval (rt-05): how well `router.classify_query` routes, before it may cut modules.

    uv run python -m seller_pulse.evals.route_eval [--model X] [--runs N] [--pace S] [--json] [--no-report]

Live, never a pytest test: it calls Groq. `score_run` and `gate` are pure and pytest-tested
with fakes. Each case is classified once per run, sequentially, with no history, through the
same `classify_query` the app uses — so a fallback counts as `ALL_ROUTES`, as it would live.

Headline metrics cover the non-deferred cases only. Deferred cases (gold carries `memory`,
which the classifier can't emit) are reported in their own section with `memory` removed from
gold, and never feed the gate.

Calls are paced (`--pace`, default `PACE_S`): Groq's free tier allows 8,000 tokens/min per
model and one call is ~600 tokens, so back-to-back calls hit 429s, the SDK's retry backoff
blows the classifier timeout, and the eval measures the rate limiter instead of the model.

The gate (rt-05's decision rule): `policy` recall = 100% and `data` recall ≥ 95%, on every run,
with no fallbacks — a fallback routes to everything, so it would "hit" every gold route and
say nothing about the classifier.
Exit codes mirror `agent_eval`: 0 gate met, 1 gate missed, 2 the eval could not run.
"""

import asyncio
import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from seller_pulse.config import PROJECT_ROOT, load_settings
from seller_pulse.evals.agent_eval import REPORTS_DIR, _fail, _git
from seller_pulse.evals.retrieval_eval import HarnessError
from seller_pulse.evals.route_cases import RouteCase, load_route_cases
from seller_pulse.llm import get_router_client
from seller_pulse.router import (
    ALL_ROUTES,
    DEFERRED_ROUTES,
    FEW_SHOT_IDS,
    STRUCTURED_OUTPUT,
    Route,
    RouteDecision,
    classify_query,
)

POLICY_RECALL_MIN = Fraction(1)
DATA_RECALL_MIN = Fraction(95, 100)
PACE_S = 5.0  # ~12 calls/min × ~600 tokens stays under the 8,000 TPM limit
ROUTES = sorted(ALL_ROUTES)  # report order: data, policy, reviews


@dataclass(frozen=True)
class CaseResult:
    case: RouteCase
    decision: RouteDecision

    @property
    def gold(self) -> frozenset[Route]:
        """Gold without deferred routes: what the classifier could possibly get right."""
        return self.case.routes - DEFERRED_ROUTES

    @property
    def predicted(self) -> frozenset[Route]:
        return self.decision.routes

    @property
    def exact(self) -> bool:
        return self.gold == self.predicted


def _labels(routes: frozenset[Route]) -> list[str]:
    return sorted(r.value for r in routes)


def _ratio(hits: int, total: int) -> dict[str, Any]:
    return {"hits": hits, "total": total, "rate": round(hits / total, 3) if total else None}


def _recall(results: list[CaseResult], route: Route) -> dict[str, Any]:
    relevant = [r for r in results if route in r.gold]
    return _ratio(sum(route in r.predicted for r in relevant), len(relevant))


def _precision(results: list[CaseResult], route: Route) -> dict[str, Any]:
    picked = [r for r in results if route in r.predicted]
    return _ratio(sum(route in r.gold for r in picked), len(picked))


def p95(values: list[int]) -> int | None:
    """Nearest-rank p95: the smallest value with ≥ 95% of the samples at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _subset(results: list[CaseResult]) -> dict[str, Any]:
    return {
        "cases": len(results),
        "exact": _ratio(sum(r.exact for r in results), len(results)),
        "policy_recall": _recall(results, Route.POLICY),
        "data_recall": _recall(results, Route.DATA),
    }


def result_to_json(result: CaseResult) -> dict[str, Any]:
    return {
        "id": result.case.id,
        "query": result.case.query,
        "gold": _labels(result.gold),
        "predicted": _labels(result.predicted),
        "exact": result.exact,
        "fallback": result.decision.fallback,
        "latency_ms": result.decision.latency_ms,
        "few_shot": result.case.id in FEW_SHOT_IDS,
    }


def score_run(results: list[CaseResult]) -> dict[str, Any]:
    """Every rt-05 metric for one run. Deferred cases are split out, never scored."""
    scored = [r for r in results if not r.case.deferred]
    deferred = [r for r in results if r.case.deferred]
    latencies = [r.decision.latency_ms for r in scored]
    return {
        "cases": len(scored),
        "policy_recall": _recall(scored, Route.POLICY),
        "routes": {
            r.value: {"precision": _precision(scored, r), "recall": _recall(scored, r)} for r in ROUTES
        },
        "exact": _ratio(sum(r.exact for r in scored), len(scored)),
        "fallbacks": sum(r.decision.fallback for r in scored),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies)) if latencies else None,
            "p95": p95(latencies),
            "max": max(latencies, default=None),
        },
        "few_shot": _subset([r for r in scored if r.case.id in FEW_SHOT_IDS]),
        "held_out": _subset([r for r in scored if r.case.id not in FEW_SHOT_IDS]),
        "misses": [result_to_json(r) for r in scored if not r.exact],
        "deferred": [result_to_json(r) for r in deferred],
    }


def _meets(ratio: dict[str, Any], minimum: Fraction) -> bool:
    # Exact arithmetic, as `agent_eval.meets_threshold`: 19/20 sits exactly on the 95% bar.
    return ratio["total"] == 0 or Fraction(ratio["hits"], ratio["total"]) >= minimum


def gate(summary: dict[str, Any]) -> bool:
    """rt-05's decision rule for one run: no fallbacks, all of policy, and ≥ 95% of data."""
    return summary["fallbacks"] == 0 and _meets(summary["policy_recall"], POLICY_RECALL_MIN) and _meets(
        summary["routes"][Route.DATA.value]["recall"], DATA_RECALL_MIN
    )


def unstable(runs: list[list[CaseResult]]) -> list[dict[str, Any]]:
    """Cases whose predicted route set differed between runs (temperature 0 isn't a guarantee)."""
    by_id: dict[str, list[CaseResult]] = {}
    for run in runs:
        for result in run:
            by_id.setdefault(result.case.id, []).append(result)
    return [
        {"id": case_id, "predicted": [_labels(r.predicted) for r in results]}
        for case_id, results in by_id.items()
        if len({r.predicted for r in results}) > 1
    ]


# --- run


async def run_once(model: BaseChatModel, cases: list[RouteCase], pace_s: float = 0) -> list[CaseResult]:
    # `classify_query` never raises; an outage shows up as fallbacks, which fail the gate.
    results = []
    for i, case in enumerate(cases):
        if i and pace_s:
            await asyncio.sleep(pace_s)  # outside the timed call: latency stays the model's
        results.append(CaseResult(case, await classify_query(model, case.message, [])))
    return results


async def run_eval(
    model: BaseChatModel, cases: list[RouteCase], n_runs: int, *, pace_s: float, json_mode: bool
) -> tuple[list[list[CaseResult]], list[dict[str, Any]]]:
    # One event loop for every run: the Groq async client must not outlive the loop it was used on.
    runs, summaries = [], []
    for i in range(1, n_runs + 1):
        if i > 1:
            await asyncio.sleep(pace_s)
        results = await run_once(model, cases, pace_s)
        summary = score_run(results)
        runs.append(results)
        summaries.append(summary)
        if json_mode:
            print(json.dumps({"run": i, **summary}, ensure_ascii=False), flush=True)
        else:
            render_run(i, summary)
    return runs, summaries


# --- human log


def _pct(ratio: dict[str, Any]) -> str:
    rate = "n/a" if ratio["rate"] is None else f"{ratio['rate']:.1%}"
    return f"{ratio['hits']}/{ratio['total']} ({rate})"


def _line(result: dict[str, Any]) -> str:
    flag = "  [fallback]" if result["fallback"] else ""
    return f"  {result['id']}  gold {result['gold']}  predicted {result['predicted']}{flag}\n    {result['query']}"


def render_run(index: int, summary: dict[str, Any]) -> None:
    latency = summary["latency_ms"]
    print(f"run {index}: {'PASS' if gate(summary) else 'FAIL'}  ({summary['cases']} cases)")
    print(f"  policy recall {_pct(summary['policy_recall'])}   exact {_pct(summary['exact'])}   "
          f"fallbacks {summary['fallbacks']}")
    for route, scores in summary["routes"].items():
        print(f"  {route:<8} precision {_pct(scores['precision'])}   recall {_pct(scores['recall'])}")
    print(f"  latency mean {latency['mean']} ms  p95 {latency['p95']} ms  max {latency['max']} ms")
    for name in ("few_shot", "held_out"):
        subset = summary[name]
        print(f"  {name:<8} exact {_pct(subset['exact'])}   policy {_pct(subset['policy_recall'])}   "
              f"data {_pct(subset['data_recall'])}")
    if summary["misses"]:
        print("  misses:")
        for miss in summary["misses"]:
            print(_line(miss))
    print("  deferred (informational, memory removed from gold):")
    for result in summary["deferred"]:
        print(_line(result))
    print()


# --- report


def build_report(
    model: str,
    run_summaries: list[dict[str, Any]],
    flips: list[dict[str, Any]],
    run_at: datetime,
    pace_s: float = PACE_S,
) -> dict[str, Any]:
    return {
        "run_at": run_at.isoformat(timespec="seconds"),
        "git_sha": _git("rev-parse", "--short", "HEAD") or "unknown",
        "dirty": bool(_git("status", "--porcelain")),
        "router_model": model,
        "temperature": 0,
        "reasoning_effort": "low",
        "structured_output": STRUCTURED_OUTPUT,
        "pace_s": pace_s,
        "gate": {"max_fallbacks": 0, "policy_recall_min": float(POLICY_RECALL_MIN), "data_recall_min": float(DATA_RECALL_MIN)},
        "passed": all(gate(s) for s in run_summaries),
        "unstable": flips,
        "runs": run_summaries,
    }


def write_report(report: dict[str, Any], run_at: datetime, reports_dir: Path | None = None) -> Path:
    reports_dir = reports_dir or REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    # The model is in the name too: candidates run side by side would otherwise share a path.
    model = report["router_model"].rsplit("/", 1)[-1]
    path = reports_dir / f"route-{run_at:%Y%m%dT%H%M%S}-{report['git_sha']}-{model}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# --- CLI


def _option(argv: list[str], flag: str) -> str | None:
    if flag not in argv:
        return None
    i = argv.index(flag)
    if i + 1 >= len(argv):
        raise HarnessError(f"{flag} needs a value")
    return argv[i + 1]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    json_mode = "--json" in argv

    try:
        settings = load_settings()
        if not settings.groq_api_key:
            raise HarnessError("GROQ_API_KEY is not set — the route eval calls Groq live")
        model_name = _option(argv, "--model") or settings.router_model
        runs_arg = _option(argv, "--runs") or "1"
        if not runs_arg.isdigit() or int(runs_arg) < 1:
            raise HarnessError(f"--runs must be a positive integer: {runs_arg!r}")
        pace_arg = _option(argv, "--pace")
        try:
            pace_s = PACE_S if pace_arg is None else float(pace_arg)
        except ValueError:
            raise HarnessError(f"--pace must be a number of seconds: {pace_arg!r}") from None
        cases = load_route_cases()
        model = get_router_client(settings, model_name).chat_model
    except Exception as exc:  # noqa: BLE001 - this boundary converts any setup failure to exit 2
        return _fail(f"could not run route eval: {exc}", json_mode)

    run_at = datetime.now()
    scored = sum(not c.deferred for c in cases)
    if not json_mode:
        print("SellerPulse route eval")
        print(f"router: {model_name}   temperature: 0   reasoning_effort: low   "
              f"output: {STRUCTURED_OUTPUT['method']}")
        print(f"cases: {scored} scored + {len(cases) - scored} deferred   runs: {runs_arg}   pace: {pace_s}s   "
              f"run: {run_at.isoformat(timespec='seconds')}")
        print()
        print("─" * 66)

    runs, summaries = asyncio.run(run_eval(model, cases, int(runs_arg), pace_s=pace_s, json_mode=json_mode))
    flips = unstable(runs)
    report = build_report(model_name, summaries, flips, run_at, pace_s)
    if not json_mode:
        print("─" * 66)
        if len(runs) > 1:
            print(f"unstable across runs: {[f['id'] for f in flips] or 'none'}")
        print(f"RESULT: {'PASS' if report['passed'] else 'FAIL'}  "
              f"(no fallbacks, policy recall = 100%, data recall ≥ {float(DATA_RECALL_MIN):.0%}, every run)")
    if "--no-report" not in argv:
        path = write_report(report, run_at)
        if not json_mode:
            print(f"report: {path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
