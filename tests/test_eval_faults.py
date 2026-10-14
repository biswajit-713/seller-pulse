from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from seller_pulse.config import Settings
from seller_pulse.evals.agent_eval import Pipeline, case_to_json, run_case
from seller_pulse.evals.cases import AgentCase
from seller_pulse.evals.faults import Fault, inject_fault, parse_fault
from seller_pulse.evals.judge import DimensionVerdict, PointVerdict, Verdict
from seller_pulse.rag.retrieval import RetrievalMode, RetrievalResult
from seller_pulse.router import Route, RouteDecision
from seller_pulse.tools import build_tools

SETTINGS = Settings(
    llm_provider="groq",
    groq_api_key=None,
    groq_model="test-model",
    server_port=7860,
    chroma_path=Path("unused"),
    seller_id="SELLER-001",
)
TODAY_ONLY = parse_fault({"tool": "get_sales_analytics", "code": "TIMEOUT", "args": {"period": "today"}})


def _tools(fault):
    return {t.name: t for t in inject_fault(build_tools(SETTINGS), fault)}


async def test_unscoped_fault_fails_every_call_with_the_envelope():
    tools = _tools(Fault(tool="check_inventory_status", code="TIMEOUT"))
    result = await tools["check_inventory_status"].ainvoke({"sku": "SKU-1001"})
    assert result["ok"] is False
    assert result["error"]["code"] == "TIMEOUT"
    assert "check_inventory_status" in result["error"]["message"]


async def test_scoped_fault_passes_other_calls_to_the_real_tool():
    tools = _tools(TODAY_ONLY)
    assert (await tools["get_sales_analytics"].ainvoke({"period": " Today "}))["error"]["code"] == "TIMEOUT"
    fallback = await tools["get_sales_analytics"].ainvoke({"period": "2026-09-25"})
    assert fallback["ok"] and fallback["data"]["revenue_usd"] == 6162.38
    assert (await tools["check_inventory_status"].ainvoke({"sku": "SKU-1001"}))["ok"]


def test_stand_in_keeps_name_description_and_schema():
    real = {t.name: t for t in build_tools(SETTINGS)}
    for name, tool in _tools(TODAY_ONLY).items():
        assert convert_to_openai_tool(tool) == convert_to_openai_tool(real[name])


def test_unknown_tool_is_rejected():
    with pytest.raises(ValueError, match="not in the pipeline"):
        inject_fault(build_tools(SETTINGS), Fault(tool="get_weather", code="TIMEOUT"))


@pytest.mark.parametrize(
    "raw",
    [
        "TIMEOUT",
        {"tool": "get_sales_analytics"},
        {"tool": "get_sales_analytics", "code": "SLOW"},
        {"tool": "", "code": "TIMEOUT"},
        {"tool": "get_sales_analytics", "code": "TIMEOUT", "args": ["today"]},
        {"tool": "get_sales_analytics", "code": "TIMEOUT", "when": "always"},
    ],
)
def test_malformed_fault(raw):
    with pytest.raises(ValueError):
        parse_fault(raw)


# --- run_case: the fault reaches the agent's tools


class ToolCallingModel:
    """Calls the sales tool for `today`, then answers."""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if any(getattr(m, "tool_call_id", None) for m in messages):
            return AIMessage(content="Today's sales check timed out.")
        return AIMessage(
            content="", tool_calls=[{"name": "get_sales_analytics", "args": {"period": "today"}, "id": "c1"}]
        )


class FakeClient:
    chat_model = ToolCallingModel()


class FakeRetriever:
    def retrieve(self, question):
        return RetrievalResult(mode=RetrievalMode.GENERAL, question=question)


class FakeJudgeModel:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        ok = DimensionVerdict(result="pass", reasons=["ok"], missed=[])
        return Verdict(suspects=[], points=[PointVerdict(point=1, met=True, evidence="ok")], accuracy=ok, grounded=ok)


async def _classify(question, history):
    return RouteDecision(routes=frozenset({Route.DATA}), fallback=False, latency_ms=1)


async def test_run_case_injects_the_case_fault():
    case = AgentCase(
        id="AE-20", source_query="SQ-37", status="scored", bucket="fault", checks=[], must=("Says it failed.",),
        why="", query="How are my sales today?", query_context=None, expected_behavior="", expected_answer="",
        notes=None, fault=TODAY_ONLY,
    )
    pipeline = Pipeline(
        client=FakeClient(), retriever=FakeRetriever(), tools=build_tools(SETTINGS), classify=_classify,
        judge_model=FakeJudgeModel(), count_tokens=len,
    )
    run = await run_case(case, pipeline)
    [call] = run.trace
    assert call.result["error"]["code"] == "TIMEOUT"
    assert case_to_json(run)["fault"] == {"tool": "get_sales_analytics", "code": "TIMEOUT", "args": {"period": ["today"]}}
    assert pipeline.tools[0].name == "get_sales_analytics"  # the pipeline's own tools are untouched
    assert (await pipeline.tools[0].ainvoke({"period": "today"}))["error"]["code"] == "NO_DATA_FOR_PERIOD"
