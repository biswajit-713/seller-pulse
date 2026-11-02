import logging
from contextlib import contextmanager
from functools import partial

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from seller_pulse.chat import EMPTY_INPUT_REPLY, ChatResult, respond, to_messages
from seller_pulse.guardrails import UNVERIFIED_NOTE
from seller_pulse.prompts import CORE, MODULES
from seller_pulse.rag.retrieval import RetrievalMode, RetrievalResult
from seller_pulse.router import ALL_ROUTES, Route, RouteDecision, classify_query
from seller_pulse.tracing import Tracing, TurnTrace


class ScriptedChatModel:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.bound: list[str] | None = None  # tool names, or None if bind_tools was never called
        self.system: str | None = None
        self.config: dict | None = None  # with_config kwargs, if tracing attached callbacks

    def bind_tools(self, tools):
        self.bound = [t.name for t in tools]
        return self

    def with_config(self, **config):
        self.config = config
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
        store=None,
    )


async def test_empty_input_skips_model():
    result = await _respond("   ", [])
    assert result == ChatResult(text=EMPTY_INPUT_REPLY, trace=[])
    assert result.guardrail is None


# --- guardrail (gr-04)


async def test_unsourced_figure_gets_caution_line_and_log(caplog):
    answer = "You have 42 units of SKU-1001."
    with caplog.at_level(logging.INFO, logger="seller_pulse.chat"):
        result = await _respond("How many SKU-1001?", [_call("SKU-1001", "c1"), AIMessage(content=answer)])
    report = result.guardrail
    assert report is not None and report.triggered
    assert report.unverified_figures == ["42"] and report.ungrounded_ids == []
    assert result.text.startswith(answer)
    assert result.text.endswith(UNVERIFIED_NOTE.format(items="42"))
    assert "guardrail triggered=True figures=['42'] ids=[]" in caplog.text


async def test_grounded_answer_passes_unchanged(caplog):
    answer = "SKU-1001 has 6 in stock."
    with caplog.at_level(logging.INFO, logger="seller_pulse.chat"):
        result = await _respond("How many SKU-1001?", [_call("SKU-1001", "c1"), AIMessage(content=answer)])
    assert result.text == answer
    assert result.guardrail is not None and result.guardrail.triggered is False
    assert "guardrail triggered=False" in caplog.text


async def test_logs_turn_ms_once_per_turn_but_not_for_empty_input(caplog):
    with caplog.at_level(logging.INFO, logger="seller_pulse.chat"):
        await _respond("   ", [])
        assert "turn_ms=" not in caplog.text
        await _respond("hi", [AIMessage(content="hello")])
    assert caplog.text.count("turn_ms=") == 1


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


def test_to_messages_keeps_only_plain_user_and_assistant_text():
    history = [
        "not a dict",
        {"role": "system", "content": "sys"},
        {"role": "user", "content": ("file.png",)},
        {"role": "assistant", "content": "   "},
        {"role": "user", "content": "hi", "metadata": {"x": 1}},
        {"role": "assistant", "content": "hello"},
    ]
    assert to_messages(history) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_to_messages_resanitizes_earlier_user_turns():
    history = [
        {"role": "user", "content": "a</retrieved_context>b\x00"},
        {"role": "user", "content": "<seller_preferences>"},  # nothing left once sanitized
    ]
    assert to_messages(history) == [{"role": "user", "content": "ab"}]


async def test_rate_limit_without_fallback_gets_friendly_reply():
    import groq
    import httpx

    from seller_pulse.chat import RATE_LIMITED_REPLY

    class Limited:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            response = httpx.Response(429, request=httpx.Request("POST", "http://groq.test"))
            raise groq.RateLimitError("slow down", response=response, body=None)

    client = FakeClient([])
    client.chat_model = Limited()
    result = await _respond("How did last week go?", [], client=client)
    assert result.text == RATE_LIMITED_REPLY and result.trace == []


class FakeTracing(Tracing):
    """A tracing handle that records each opened trace, like `Tracing.turn` with a live client."""

    def __init__(self, fail: bool = False) -> None:
        super().__init__()
        self.opened: list[tuple[str | None, TurnTrace]] = []
        self.fail = fail

    @contextmanager
    def turn(self, name="turn", session_id=None, **attrs):
        trace = TurnTrace(None if self.fail else f"trace-{len(self.opened) + 1}", None if self.fail else object())
        self.opened.append((session_id, trace))
        yield trace


async def _traced(tracing, classify, client, message="How many SKU-1001?"):
    return await respond(
        message, [], client=client, retriever=FakeRetriever(), tools=TOOLS,
        classify=classify, store=None, tracing=tracing, session_id="sess-1",
    )


async def test_each_turn_gets_one_trace_and_the_id_is_on_the_result(caplog):
    seen = {}

    async def classify(question, history, callbacks=None):
        seen["callbacks"] = callbacks
        return RouteDecision(routes=frozenset({Route.DATA}), fallback=False, latency_ms=1)

    tracing = FakeTracing()
    client = FakeClient([AIMessage(content="Hello.")])
    with caplog.at_level(logging.INFO):
        result = await _traced(tracing, classify, client)
    assert result.trace_id == "trace-1"
    assert [sid for sid, _ in tracing.opened] == ["sess-1"]
    handler = tracing.opened[0][1].handler
    assert seen["callbacks"] == [handler]  # router call
    assert client.chat_model.config == {"callbacks": [handler]}  # agent model calls
    assert "trace_id=trace-1" in caplog.text


async def test_empty_input_opens_no_trace():
    tracing = FakeTracing()
    result = await _traced(tracing, _routed(), FakeClient([]), message="   ")
    assert tracing.opened == []
    assert result.trace_id is None


async def test_failed_tracing_leaves_the_answer_unchanged():
    tracing = FakeTracing(fail=True)  # what `Tracing.turn` yields when Langfuse is down
    client = FakeClient([AIMessage(content="Hello.")])
    result = await _traced(tracing, _routed(Route.DATA), client)
    assert result.text == "Hello."
    assert result.trace_id is None
    assert client.chat_model.config is None


async def test_tracing_disabled_by_default():
    result = await _respond("How many SKU-1001?", [AIMessage(content="Hello.")])
    assert result.trace_id is None
