import json

import pytest

from seller_pulse.evals.cases import DEFAULT_AGENT_CASES_PATH, load_cases
from seller_pulse.evals.retrieval_eval import HarnessError

QUERIES = [
    {"id": "SQ-01", "query": "How did last week go?", "expected_behavior": "Use the tool.",
     "expected_answer": "904 orders.", "notes": "last_7_days accepted"},
    {"id": "SQ-03", "query": "Draft a reply.", "query_context": "Rug took 3 weeks.",
     "expected_behavior": "Label it a draft.", "expected_answer": "Sorry..."},
]
CASE = {"id": "AE-01", "source_query": "SQ-01", "status": "scored", "bucket": "sales",
        "checks": [{"kind": "tool_called", "name": "get_sales_analytics"}],
        "must": ["States the window."], "why": "headline"}


def _write(tmp_path, cases, queries=QUERIES):
    cases_path, queries_path = tmp_path / "cases.jsonl", tmp_path / "queries.jsonl"
    queries_path.write_text("\n".join(json.dumps(q) for q in queries) + "\n")
    cases_path.write_text("\n".join(c if isinstance(c, str) else json.dumps(c) for c in cases) + "\n")
    return cases_path, queries_path


def _case(**overrides):
    return {**CASE, **overrides}


def test_joins_query_fields(tmp_path):
    [case] = load_cases(*_write(tmp_path, [CASE]))
    assert case.query == "How did last week go?"
    assert case.query_context is None
    assert case.message == case.query
    assert case.rubric.expected_answer == "904 orders."
    assert case.rubric.notes == "last_7_days accepted"
    assert case.rubric.must == ("States the window.",)
    assert case.scored


def test_query_context_appended_to_message(tmp_path):
    [case] = load_cases(*_write(tmp_path, [_case(source_query="SQ-03", status="known_gap")]))
    assert case.message == "Draft a reply.\nRug took 3 weeks."
    assert case.rubric.query_context == "Rug took 3 weeks."
    assert case.rubric.notes is None
    assert not case.scored


def test_groundedness_allow_values(tmp_path):
    allow = [{"value": "21", "why": "query implies three weeks"}]
    [case] = load_cases(*_write(tmp_path, [_case(groundedness_allow=allow)]))
    assert case.groundedness_allow == ("21",)


@pytest.mark.parametrize(
    "cases, message",
    [
        ([_case(source_query="SQ-99")], "SQ-99"),
        ([CASE, CASE], "duplicate"),
        (["{not json"], "malformed JSON"),
        ([{k: v for k, v in CASE.items() if k != "bucket"}], "missing"),
        ([_case(status="draft")], "status"),
        ([_case(checks=[{"kind": "telepathy"}])], "malformed check"),
        ([_case(checks=[{"kind": "contains_all"}])], "malformed check"),
        ([_case(checks=[{"kind": "contains_all", "needles": ["x"], "dimension": "behavior"}])], "malformed check"),
        ([_case(groundedness_allow=["21"])], "groundedness_allow"),
        ([{k: v for k, v in CASE.items() if k != "must"}], "missing"),
        ([_case(must=[])], "must"),
        ([_case(must="States the window.")], "must"),
        ([_case(must=["ok", " "])], "must"),
    ],
)
def test_bad_case_file_raises_harness_error(tmp_path, cases, message):
    with pytest.raises(HarnessError, match=message):
        load_cases(*_write(tmp_path, cases))


def test_real_case_file_loads():
    cases = load_cases()
    assert len(cases) == 18
    assert sum(c.scored for c in cases) == 15
    assert DEFAULT_AGENT_CASES_PATH.exists()
