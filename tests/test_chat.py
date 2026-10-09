import logging
from functools import partial

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from seller_pulse.chat import EMPTY_INPUT_REPLY, ChatResult, respond
from seller_pulse.prompts import CORE, MODULES
from seller_pulse.rag.retrieval import RetrievalMode, RetrievalResult
from seller_pulse.router import ALL_ROUTES, Route, RouteDecision, classify_query


class ScriptedChatModel:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.bound: list[str] | None = None  # tool names, or None if bind_tools was never called
        self.system: str | None = None

    def bind_tools(self, tools):
        self.bound = [t.name for t in tools]
        return self

    async def ainvoke(self, messages):
        self.system = messages[0].content
        return self.replies.pop(0)


class FakeClient:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.chat_model = ScriptedChatModel(replies)


class FakeRetriever:
    def retrieve(self, question: str) -> RetrievalResult:
        return RetrievalResult(mode=RetrievalMode.GENERAL, question=question)


def _stock(sku: str) -> dict:
    if sku == "SKU-9999":
        return {"ok": False, "error": {"code": "SKU_NOT_FOUND", "message": "nope"}}
    return {"ok": True, "data": {"sku": sku, "stock_qty": 6}}


STOCK = StructuredTool.from_function(func=_stock, name="check_inventory_status", description="Stock.")
SALES = StructuredTool.from_function(
    func=lambda period: {"ok": True, "data": {}}, name="get_sales_analytics", description="Sales."
)
TOOLS = [SALES, STOCK]


def _routed(*routes: Route, fallback: bool = False):
    async def classify(question, history):
        return RouteDecision(routes=frozenset(routes), fallback=fallback, latency_ms=1)

    return classify


def _call(sku: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "check_inventory_status", "args": {"sku": sku}, "id": call_id}],
    )


async def _respond(
    message: str, replies: list[AIMessage], classify=_routed(Route.DATA), client=None, history=()
) -> ChatResult:
    return await respond(
        message,
        list(history),
        client=client or FakeClient(replies),
        retriever=FakeRetriever(),
        tools=TOOLS,
        classify=classify,
    )


async def test_empty_input_skips_model():
    result = await _respond("   ", [])
    assert result == ChatResult(text=EMPTY_INPUT_REPLY, trace=[])


async def test_returns_text_and_trace(caplog):
    with caplog.at_level(logging.INFO, logger="seller_pulse.chat"):
        result = await _respond(
            "How many SKU-1001?", [_call("SKU-1001", "c1"), AIMessage(content="6 in stock.")]
        )
    assert result.text == "6 in stock."
    assert [r.name for r in result.trace] == ["check_inventory_status"]
    assert "check_inventory_status" in caplog.text and "ok=True" in caplog.text


async def test_logs_error_code_on_failed_call(caplog):
    with caplog.at_level(logging.INFO, logger="seller_pulse.chat"):
        await _respond(
            "SKU-9999?", [_call("SKU-9999", "c1"), AIMessage(content="Not in catalog.")]
        )
    assert "ok=False code=SKU_NOT_FOUND" in caplog.text


# --- routing (rt-06)


async def test_data_route_binds_tools_and_data_module(caplog):
    client = FakeClient([AIMessage(content="Sales were up.")])
    with caplog.at_level(logging.INFO, logger="seller_pulse.chat"):
        result = await _respond("How did last week go?", [], client=client)
    model = client.chat_model
    assert model.bound == ["get_sales_analytics", "check_inventory_status"]
    assert MODULES[Route.DATA] in model.system
    assert MODULES[Route.POLICY] not in model.system and MODULES[Route.REVIEWS] not in model.system
    assert result.routes == {Route.DATA} and result.route_fallback is False
    assert "routes=['data'] fallback=False" in caplog.text


async def test_reviews_route_binds_no_tools():
    client = FakeClient([AIMessage(content="Buyers mention shipping.")])
    result = await _respond("What do buyers complain about?", [], client=client, classify=_routed(Route.REVIEWS))
    model = client.chat_model
    assert model.bound is None  # bind_tools never called
    assert MODULES[Route.REVIEWS] in model.system
    assert MODULES[Route.DATA] not in model.system and MODULES[Route.POLICY] not in model.system
    assert result.routes == {Route.REVIEWS}


async def test_classifier_failure_falls_back_to_full_prompt_and_tools():
    class Broken:
        def with_structured_output(self, schema, **kwargs):
            raise RuntimeError("router down")

    client = FakeClient([AIMessage(content="ok")])
    result = await _respond("Anything?", [], client=client, classify=partial(classify_query, Broken()))
    model = client.chat_model
    assert model.bound == ["get_sales_analytics", "check_inventory_status"]
    for module in MODULES.values():
        assert module in model.system
    assert result.routes == ALL_ROUTES and result.route_fallback is True


async def test_empty_route_set_is_core_only():
    client = FakeClient([AIMessage(content="I can't see other sellers' data.")])
    result = await _respond("What do competitors charge?", [], client=client, classify=_routed())
    model = client.chat_model
    assert model.bound is None
    assert model.system.startswith(CORE + "\n\n")
    for module in MODULES.values():
        assert module not in model.system
    assert result.routes == frozenset()


async def test_classifier_sees_history_without_the_current_message():
    seen = {}

    async def classify(question, history):
        seen["args"] = (question, history)
        return RouteDecision(routes=frozenset(), fallback=False, latency_ms=1)

    history = [{"role": "user", "content": "Sales last week?"}, {"role": "assistant", "content": "Up 5%."}]
    await _respond("and the week before?", [AIMessage(content="ok")], classify=classify, history=history)
    assert seen["args"] == ("and the week before?", history)
