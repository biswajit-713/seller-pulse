import json

from seller_pulse.evals import route_eval
from seller_pulse.evals.route_cases import RouteCase, load_route_cases
from seller_pulse.evals.route_eval import CaseResult, gate, p95, run_once, score_run, unstable
from seller_pulse.router import ALL_ROUTES, FEW_SHOT_IDS, Route, RouteDecision

D, R, P, M = Route.DATA, Route.REVIEWS, Route.POLICY, Route.MEMORY


def _case(id, *routes):
    return RouteCase(id=id, routes=frozenset(routes), why="", query=f"query {id}", query_context=None)


def _result(case, *predicted, fallback=False, latency_ms=100):
    routes = ALL_ROUTES if fallback else frozenset(predicted)
    return CaseResult(case, RouteDecision(routes=routes, fallback=fallback, latency_ms=latency_ms))


def test_perfect_run_passes_the_gate():
    results = [_result(_case("SQ-01", D), D), _result(_case("SQ-06", P), P), _result(_case("SQ-31"))]
    summary = score_run(results)
    assert summary["policy_recall"] == {"hits": 1, "total": 1, "rate": 1.0}
    assert summary["exact"]["hits"] == 3
    assert summary["misses"] == []
    assert gate(summary)


def test_missed_policy_fails_the_gate_and_is_listed():
    summary = score_run([_result(_case("SQ-14", P), R), _result(_case("SQ-01", D), D)])
    assert summary["policy_recall"]["hits"] == 0
    assert not gate(summary)
    [miss] = summary["misses"]
    assert (miss["id"], miss["gold"], miss["predicted"]) == ("SQ-14", ["policy"], ["reviews"])


def test_data_recall_bar_is_exact_at_95_percent():
    def run(data_hits, total):
        return [_result(_case(f"SQ-{i}", D), D if i < data_hits else R) for i in range(total)]

    assert gate(score_run(run(19, 20)))  # 95.0% sits on the bar
    assert not gate(score_run(run(18, 19)))  # 94.7%


def test_extra_routes_cost_precision_not_recall():
    summary = score_run([_result(_case("SQ-01", D), D, P)])
    assert summary["routes"]["data"]["recall"]["rate"] == 1.0
    assert summary["routes"]["policy"]["precision"] == {"hits": 0, "total": 1, "rate": 0.0}
    assert summary["exact"]["hits"] == 0
    assert gate(summary)


def test_fallback_fails_the_gate_even_though_it_hits_every_route():
    summary = score_run([_result(_case("SQ-06", P), fallback=True)])
    assert summary["policy_recall"]["rate"] == 1.0
    assert summary["fallbacks"] == 1
    assert not gate(summary)


def test_deferred_cases_are_reported_but_never_scored():
    deferred = _result(_case("SQ-05", M, D), R)  # would be a data miss if it counted
    summary = score_run([_result(_case("SQ-01", D), D), deferred])
    assert summary["cases"] == 1
    assert summary["routes"]["data"]["recall"]["total"] == 1
    assert summary["misses"] == []
    [shown] = summary["deferred"]
    assert shown["gold"] == ["data"]  # memory removed
    assert gate(summary)


def test_few_shot_and_held_out_are_split():
    few_shot_id = sorted(FEW_SHOT_IDS)[0]
    summary = score_run([_result(_case(few_shot_id, D), D), _result(_case("SQ-14", P), R)])
    assert summary["few_shot"]["cases"] == 1 and summary["few_shot"]["exact"]["hits"] == 1
    assert summary["held_out"]["cases"] == 1 and summary["held_out"]["policy_recall"]["hits"] == 0


def test_latency_mean_and_p95():
    results = [_result(_case(f"SQ-{i}", D), D, latency_ms=ms) for i, ms in enumerate(range(100, 2100, 100))]
    latency = score_run(results)["latency_ms"]
    assert latency["mean"] == 1050
    assert latency["p95"] == 1900  # nearest rank: 19th of 20
    assert p95([]) is None


def test_unstable_lists_only_cases_that_changed():
    a, b = _case("SQ-01", D), _case("SQ-02", D, R)
    runs = [[_result(a, D), _result(b, D, R)], [_result(a, D), _result(b, D)]]
    assert unstable(runs) == [{"id": "SQ-02", "predicted": [["data", "reviews"], ["data"]]}]


def test_real_case_file_has_31_scored_and_6_deferred():
    cases = load_route_cases()
    assert sum(not c.deferred for c in cases) == 31
    assert sorted(c.id for c in cases if c.deferred) == ["SQ-05", "SQ-16", "SQ-22", "SQ-23", "SQ-33", "SQ-36"]


class EchoGoldModel:
    """A perfect classifier: answers each message with its case's gold (minus deferred)."""

    def __init__(self, cases):
        self.gold = {c.message: sorted(r.value for r in c.routes if r in ALL_ROUTES) for c in cases}

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        message = messages[-1].content.split("Message to route:\n", 1)[1]
        return self.schema.model_validate({"routes": self.gold[message]})


async def test_run_once_through_classify_query_scores_a_perfect_model():
    cases = load_route_cases()
    summary = score_run(await run_once(EchoGoldModel(cases), cases))
    assert summary["exact"] == {"hits": 31, "total": 31, "rate": 1.0}
    assert summary["fallbacks"] == 0
    assert gate(summary)


def test_report_name_and_shape(tmp_path):
    from datetime import datetime

    run_at = datetime(2026, 10, 8, 9, 30, 0)
    summary = score_run([_result(_case("SQ-01", D), D)])
    report = route_eval.build_report("openai/gpt-oss-20b", [summary], [], run_at)
    path = route_eval.write_report(report, run_at, tmp_path)
    assert path.name == f"route-20261008T093000-{report['git_sha']}-gpt-oss-20b.json"
    loaded = json.loads(path.read_text())
    assert loaded["router_model"] == "openai/gpt-oss-20b"
    assert loaded["passed"] is True
    assert loaded["structured_output"] == {"method": "json_schema", "strict": True}


def test_missing_api_key_is_exit_2(monkeypatch, capsys):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("GROQ_API_KEY", "")
    assert route_eval.main(["--json"]) == 2
    assert "GROQ_API_KEY" in json.loads(capsys.readouterr().out)["error"]


def test_bad_runs_flag_is_exit_2(monkeypatch, capsys):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("GROQ_API_KEY", "fake")
    assert route_eval.main(["--runs", "0", "--json"]) == 2
    assert "--runs" in json.loads(capsys.readouterr().out)["error"]
