import sys

import pytest

from seller_pulse.config import load_settings
from seller_pulse.tracing import NO_TRACE, Tracing, build_tracing

KEYS = ("TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)


def test_off_without_keys_and_never_imports_langfuse():
    sys.modules.pop("langfuse", None)
    tracing = build_tracing(load_settings())
    assert not tracing.enabled
    with tracing.turn() as t:
        assert t is NO_TRACE
    tracing.flush()
    assert "langfuse" not in sys.modules


def test_off_when_flag_off_even_with_keys(monkeypatch):
    monkeypatch.setenv("TRACING", "off")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert not build_tracing(load_settings()).enabled


def test_one_key_is_not_enough(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    assert not load_settings().tracing_active


def test_blank_host_is_none(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "")
    assert load_settings().langfuse_host is None


class BrokenClient:
    def create_trace_id(self):
        raise RuntimeError("langfuse down")

    def flush(self):
        raise RuntimeError("langfuse down")


def test_client_errors_are_swallowed_and_logged(caplog):
    tracing = Tracing(BrokenClient())
    with tracing.turn() as t:
        assert t is NO_TRACE
    tracing.flush()
    assert "could not start trace" in caplog.text
    assert "flush failed" in caplog.text


def test_body_exceptions_propagate():
    with pytest.raises(ValueError):
        with Tracing().turn():
            raise ValueError("boom")


# --- w4-04: events and scores -------------------------------------------------------------

from seller_pulse.agent import ToolCallRecord
from seller_pulse.guardrails import GuardrailReport
from seller_pulse.rag.retrieval import Hit, RetrievalMode, RetrievalResult
from seller_pulse.router import Route, RouteDecision
from seller_pulse.tracing import TurnTrace


class FakeObservation:
    def end(self):
        pass


class RecordingClient:
    def __init__(self):
        self.spans, self.scores, self.updates = [], {}, []

    def start_observation(self, **kw):
        self.spans.append(kw)
        return FakeObservation()

    def create_score(self, **kw):
        assert kw["trace_id"] == "t1" and kw["data_type"] == "NUMERIC"
        self.scores[kw["name"]] = kw["value"]

    def update_current_span(self, **kw):
        self.updates.append(kw)


def _record(calls, report=None, embed=(1, 0), client=None):
    client = client or RecordingClient()
    report = report or GuardrailReport([], [], False, False, False, [])
    retrieved = RetrievalResult(
        mode=RetrievalMode.GENERAL,
        question="q",
        reviews=(Hit("R1", "text", 0.2, {}, "c"),),
    )
    Tracing(client).record_turn(
        TurnTrace("t1", object()),
        decision=RouteDecision(frozenset({Route.DATA}), False, 5),
        retrieved=retrieved, embed_cache=embed, tool_calls=calls, report=report, turn_ms=42,
    )
    return client


def test_clean_turn_scores_zero():
    client = _record([ToolCallRecord("t", {}, {"ok": True}, cached=True, latency_ms=3)])
    assert client.scores == {"tool_failures": 0, "tool_calls": 1, "guardrail_triggered": 0}
    assert [s["name"] for s in client.spans] == ["route", "retrieval", "t", "guardrail"]
    retrieval = client.spans[1]["metadata"]
    assert retrieval["hits"] == [{"id": "R1", "distance": 0.2}] and retrieval["embed_cache_hits"] == 1
    assert client.spans[2]["metadata"]["cached"] is True
    assert client.spans[2]["level"] is None
    assert client.updates == [{"metadata": {"turn_ms": 42}}]


def test_failed_tool_call_is_an_error_span():
    bad = ToolCallRecord("find", {"sku": "X"}, {"ok": False, "error": {"code": "NOT_FOUND"}})
    client = _record([bad])
    span = client.spans[2]
    assert span["level"] == "ERROR" and "NOT_FOUND" in span["status_message"]
    assert client.scores["tool_failures"] == 1


def test_triggered_guardrail_scores_one():
    client = _record([], GuardrailReport(["9"], [], False, False, False, []))
    assert client.scores["guardrail_triggered"] == 1
    assert client.spans[-1]["metadata"]["unverified_figures"] == ["9"]


def test_record_turn_is_a_noop_without_a_trace_and_swallows_errors(caplog):
    assert _record([], client=RecordingClient()).spans  # sanity: records when traced
    Tracing().record_turn(TurnTrace(), decision=None, retrieved=None, embed_cache=None, tool_calls=[], report=None, turn_ms=0)
    Tracing(BrokenClient()).record_turn(TurnTrace("t1", object()), decision=None, retrieved=None, embed_cache=None, tool_calls=[], report=None, turn_ms=0)
    assert "could not record turn events" in caplog.text


def test_input_rail_span_and_score():
    from seller_pulse.input_rails import RailVerdict

    client = RecordingClient()
    Tracing(client).record_input_rail(TurnTrace("t1", object()), RailVerdict(True, 500))
    assert client.scores == {"input_rail_blocked": 1.0}
    assert client.spans[0]["name"] == "input_rail" and client.spans[0]["metadata"]["blocked"] is True
