import json

import pytest
from langchain_core.messages import AIMessage

from seller_pulse.config import Settings
from seller_pulse.evals import agent_eval
from seller_pulse.evals.agent_eval import Pipeline, meets_threshold, resolve_dimensions, run_case, summarize
from seller_pulse.evals.cases import AgentCase
from seller_pulse.evals.checks import CheckKind, CheckResult, Dimension
from seller_pulse.evals.judge import DimensionVerdict, PointVerdict, SuspectVerdict, Verdict
from seller_pulse.rag.retrieval import RetrievalMode, RetrievalResult
from seller_pulse.router import Route, RouteDecision

PASS = DimensionVerdict(result="pass", reasons=["ok"], missed=[])
FAIL = DimensionVerdict(result="fail", reasons=["no"], missed=["the caveat"])
NA = DimensionVerdict(result="n/a", reasons=[], missed=[])


MUST = ("States the window.",)
MET = [PointVerdict(point=1, met=True, evidence="ok")]
UNMET = [PointVerdict(point=1, met=False, evidence="no window")]


def _verdict(accuracy=PASS, grounded=PASS, points=MET, suspects=()):
    return Verdict(suspects=list(suspects), points=list(points), accuracy=accuracy, grounded=grounded)


def _check(dimension, passed=True):
    return CheckResult(kind=CheckKind.CONTAINS_ALL, dimension=dimension, passed=passed, detail="")


def _case(id="AE-01", status="scored", bucket="sales", checks=()):
    return AgentCase(
        id=id, source_query="SQ-01", status=status, bucket=bucket, checks=list(checks), must=MUST, why="",
        query="How did last week go?", query_context=None, expected_behavior="Use the tool.",
        expected_answer="Good.", notes=None,
    )


# --- fakes


class ScriptedChatModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content=self.replies.pop(0))


class FakeClient:
    def __init__(self, replies: list[str]) -> None:
        self.chat_model = ScriptedChatModel(replies)


class FakeRetriever:
    def retrieve(self, question: str) -> RetrievalResult:
        return RetrievalResult(mode=RetrievalMode.GENERAL, question=question)


class FakeJudgeModel:
    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        return self.verdict


async def _classify(question, history):
    return RouteDecision(routes=frozenset({Route.DATA}), fallback=False, latency_ms=1)


def _pipeline(replies, verdict=None):
    return Pipeline(
        client=FakeClient(replies), retriever=FakeRetriever(), tools=[], classify=_classify,
        judge_model=FakeJudgeModel(verdict or _verdict()),
    )


# --- resolve_dimensions


def test_fail_beats_pass():
    dims = resolve_dimensions([_check(Dimension.ACCURACY), _check(Dimension.ACCURACY, False)], _verdict())
    assert dims["accuracy"] == "fail"


def test_judge_fail_beats_check_pass():
    assert resolve_dimensions([_check(Dimension.ACCURACY)], _verdict(accuracy=FAIL))["accuracy"] == "fail"


def test_pass_with_no_fails_and_na_when_nothing_applies():
    dims = resolve_dimensions([], _verdict(accuracy=NA, grounded=NA), must=MUST)
    assert dims == {"tool_use": "n/a", "accuracy": "n/a", "grounded": "n/a", "behavior": "pass"}


@pytest.mark.parametrize(
    "points, expected",
    [
        (MET, "pass"),
        (UNMET, "fail"),
        ([], "fail"),  # point not returned by the judge
        ([*MET, PointVerdict(point=2, met=False, evidence="extra")], "pass"),  # unknown point ignored
    ],
)
def test_behavior_is_one_result_per_must_point(points, expected):
    assert resolve_dimensions([], _verdict(points=points), must=MUST)["behavior"] == expected


def test_accuracy_fail_does_not_fail_behavior():
    dims = resolve_dimensions([], _verdict(accuracy=FAIL), must=MUST)
    assert dims["accuracy"] == "fail" and dims["behavior"] == "pass"


def test_tool_use_ignores_the_judge():
    judge_error = Verdict(suspects=[], points=[], accuracy=FAIL, grounded=FAIL, judge_error=True)
    assert resolve_dimensions([_check(Dimension.TOOL_USE)], judge_error)["tool_use"] == "pass"
    assert resolve_dimensions([], judge_error)["tool_use"] == "n/a"


def test_ungrounded_check_fails_despite_passing_judge():
    dims = resolve_dimensions([_check(Dimension.GROUNDED, False)], _verdict())
    assert dims["grounded"] == "fail"


@pytest.mark.parametrize(
    "suspects, expected",
    [
        ([SuspectVerdict(value="9.6%", classification="fabricated", basis="no source")], "fail"),
        ([], "fail"),  # suspect absent from the verdict
        ([SuspectVerdict(value="9.6", classification="derived", basis="(1000-904)/1000")], "pass"),
        ([SuspectVerdict(value="9.6%", classification="derived", basis="judge echoed the %")], "pass"),
    ],
)
def test_suspect_classification(suspects, expected):
    dims = resolve_dimensions([_check(Dimension.GROUNDED)], _verdict(suspects=suspects), ["9.6"])
    assert dims["grounded"] == expected


# --- run_case


async def test_run_case_passes_only_when_no_dimension_fails():
    run = await run_case(_case(checks=[{"kind": "contains_all", "needles": ["fine"]}]), _pipeline(["All fine."]))
    assert run.passed and run.dimensions["accuracy"] == "pass"
    assert "<retrieved_context>" in run.retrieved_context
    assert run.routes == {Route.DATA} and not run.route_fallback
    assert agent_eval.case_to_json(run)["routes"] == ["data"]

    run = await run_case(_case(), _pipeline(["All fine."], _verdict(points=UNMET)))
    assert not run.passed


async def test_ungrounded_id_fails_case_with_passing_judge():
    run = await run_case(_case(), _pipeline(["SKU-4242 is your best seller."]))
    assert run.groundedness.ungrounded_ids == ["SKU-4242"]
    assert run.dimensions["grounded"] == "fail"
    assert not run.passed


async def test_unclassified_suspect_fails_grounded():
    run = await run_case(_case(), _pipeline(["Sales fell 9.6%."]))
    assert run.groundedness.suspects == ["9.6"]
    assert run.dimensions["grounded"] == "fail"


# --- summarize


def _run(case, dims):
    return agent_eval.CaseRun(
        case=case, answer="", trace=[], routes=frozenset(), route_fallback=False, retrieved_context="",
        checks=[], groundedness=None,
        verdict=_verdict(), dimensions=dims, latency_ms=100,
    )


ALL_PASS = {"tool_use": "pass", "accuracy": "pass", "grounded": "pass", "behavior": "pass"}


def test_summary_rates_exclude_na_and_known_gap():
    runs = [
        _run(_case("AE-01", bucket="sales"), ALL_PASS),
        _run(_case("AE-02", bucket="sales"), {**ALL_PASS, "tool_use": "n/a", "accuracy": "fail"}),
        _run(_case("AE-03", bucket="guardrail"), {**ALL_PASS, "tool_use": "n/a"}),
        _run(_case("AE-16", status="known_gap", bucket="sales"), {**ALL_PASS, "accuracy": "fail"}),
    ]
    summary = summarize(runs)
    assert summary["score"] == {"passed": 2, "scored": 3, "rate": 0.667}
    assert summary["known_gap"] == {"passed": 0, "total": 1}
    assert summary["dimensions"]["tool_use"] == {"passed": 1, "applicable": 1}
    assert summary["dimensions"]["accuracy"] == {"passed": 2, "applicable": 3}
    assert summary["buckets"] == {"sales": {"passed": 1, "total": 2}, "guardrail": {"passed": 1, "total": 1}}


def test_threshold_boundary():
    assert meets_threshold(12, 15)
    assert not meets_threshold(11, 15)


# --- main


SETTINGS = Settings(
    llm_provider="groq", groq_api_key="fake", groq_model="agent-model", server_port=0,
    chroma_path="unused", seller_id="SELLER-001", judge_model="judge-model",
)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Patch setup so `main` runs 15 scored cases + 1 known-gap against fakes."""
    cases = [_case(f"AE-{i:02d}", checks=[{"kind": "contains_all", "needles": ["fine"]}]) for i in range(1, 16)]
    cases.append(_case("AE-16", status="known_gap"))
    monkeypatch.setattr(agent_eval, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(agent_eval, "load_cases", lambda: cases)
    monkeypatch.setattr(agent_eval, "REPORTS_DIR", tmp_path / "reports")

    def use(passing: int):
        replies = ["All fine."] * passing + ["Nope."] * (15 - passing) + ["Gap."]
        monkeypatch.setattr(agent_eval, "build_pipeline", lambda settings: _pipeline(replies))
        return tmp_path / "reports"

    return use


def test_exit_0_at_threshold_and_report_written(harness, capsys):
    reports = harness(12)
    assert agent_eval.main([]) == 0
    assert "RESULT: PASS" in capsys.readouterr().out
    [path] = reports.glob("*.json")
    report = json.loads(path.read_text())
    assert path.name.endswith(f"-{report['git_sha']}.json")
    assert {"run_at", "git_sha", "dirty", "agent_model", "judge_model", "temperature", "threshold", "score",
            "known_gap", "dimensions", "buckets", "latency_ms", "cases"} <= report.keys()
    assert report["score"] == {"passed": 12, "scored": 15, "rate": 0.8}
    assert report["known_gap"]["total"] == 1
    assert [c["id"] for c in report["cases"]][-1] == "AE-16"
    case = report["cases"][0]
    assert {"id", "source_query", "bucket", "status", "passed", "dimensions", "answer", "retrieved_context",
            "trace", "checks", "groundedness", "verdict", "latency_ms"} <= case.keys()


def test_exit_1_below_threshold(harness):
    harness(11)
    assert agent_eval.main(["--no-report"]) == 1


def test_no_report_writes_nothing(harness):
    reports = harness(15)
    assert agent_eval.main(["--no-report"]) == 0
    assert not reports.exists()


def test_case_filter_and_json(harness, capsys):
    harness(15)
    assert agent_eval.main(["--case", "AE-03", "--json", "--no-report"]) == 0
    [line] = capsys.readouterr().out.strip().splitlines()
    assert json.loads(line)["id"] == "AE-03"


def test_unknown_case_is_exit_2(harness):
    harness(15)
    assert agent_eval.main(["--case", "AE-99", "--no-report"]) == 2


def test_missing_api_key_is_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(agent_eval, "load_settings", lambda: Settings(**{**SETTINGS.__dict__, "groq_api_key": None}))
    assert agent_eval.main(["--no-report"]) == 2
    assert "GROQ_API_KEY" in capsys.readouterr().out
