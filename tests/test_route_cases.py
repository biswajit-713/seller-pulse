import json

import pytest

from seller_pulse.evals.retrieval_eval import DEFAULT_QUERIES_PATH, HarnessError
from seller_pulse.evals.route_cases import load_route_cases
from seller_pulse.router import Route

QUERIES = [
    {"id": "SQ-01", "query": "How did last week go?"},
    {"id": "SQ-03", "query": "Draft a reply.", "query_context": "Rug took 3 weeks."},
]
CASE = {"id": "SQ-01", "routes": ["data"], "why": "sales tool"}


def _write(tmp_path, cases, queries=QUERIES):
    cases_path, queries_path = tmp_path / "route_cases.jsonl", tmp_path / "queries.jsonl"
    queries_path.write_text("\n".join(json.dumps(q) for q in queries) + "\n")
    cases_path.write_text("\n".join(c if isinstance(c, str) else json.dumps(c) for c in cases) + "\n")
    return cases_path, queries_path


def _case(**overrides):
    return {**CASE, **overrides}


def test_real_file_covers_every_query():
    cases = load_route_cases()
    query_ids = {json.loads(line)["id"] for line in DEFAULT_QUERIES_PATH.read_text().splitlines() if line.strip()}
    assert len(cases) == 37
    assert {c.id for c in cases} == query_ids


def test_real_file_spot_labels():
    routes = {c.id: c.routes for c in load_route_cases()}
    assert routes["SQ-14"] == {Route.POLICY}
    assert routes["SQ-28"] == {Route.DATA, Route.REVIEWS, Route.POLICY}
    assert routes["SQ-31"] == frozenset()
    assert routes["SQ-16"] == {Route.MEMORY, Route.REVIEWS}


def test_real_file_memory_cases_deferred():
    deferred = {c.id for c in load_route_cases() if c.deferred}
    assert deferred == {"SQ-05", "SQ-16", "SQ-22", "SQ-23", "SQ-33", "SQ-36"}


def test_joins_query_and_context(tmp_path):
    [plain, pasted] = load_route_cases(*_write(tmp_path, [CASE, _case(id="SQ-03", routes=["reviews"])]))
    assert plain.routes == {Route.DATA}
    assert plain.message == "How did last week go?"
    assert pasted.message == "Draft a reply.\nRug took 3 weeks."


def test_empty_routes_allowed(tmp_path):
    [case] = load_route_cases(*_write(tmp_path, [_case(routes=[])]))
    assert case.routes == frozenset()


@pytest.mark.parametrize(
    ("case", "match"),
    [
        (_case(id="SQ-99"), "not in queries.jsonl"),
        (_case(routes=["sales"]), "unknown routes"),
        (_case(routes=["data", "data"]), "duplicate routes"),
        (_case(routes="data"), "must be a list"),
        (_case(why=""), "why"),
        ({"id": "SQ-01", "routes": []}, "missing"),
        ("{not json", "malformed JSON"),
    ],
)
def test_rejects_bad_case(tmp_path, case, match):
    with pytest.raises(HarnessError, match=match):
        load_route_cases(*_write(tmp_path, [case]))


def test_rejects_duplicate_id(tmp_path):
    with pytest.raises(HarnessError, match="duplicate case id"):
        load_route_cases(*_write(tmp_path, [CASE, CASE]))
