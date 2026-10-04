import logging

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from seller_pulse.chat import EMPTY_INPUT_REPLY, ChatResult, respond
from seller_pulse.rag.retrieval import RetrievalResult, Route


class ScriptedChatModel:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self.replies.pop(0)


class FakeClient:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.chat_model = ScriptedChatModel(replies)


class FakeRetriever:
    def retrieve(self, question: str) -> RetrievalResult:
        return RetrievalResult(route=Route.GENERAL, question=question)


def _stock(sku: str) -> dict:
    if sku == "SKU-9999":
        return {"ok": False, "error": {"code": "SKU_NOT_FOUND", "message": "nope"}}
    return {"ok": True, "data": {"sku": sku, "stock_qty": 6}}


STOCK = StructuredTool.from_function(func=_stock, name="check_inventory_status", description="Stock.")


def _call(sku: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "check_inventory_status", "args": {"sku": sku}, "id": call_id}],
    )


async def _respond(message: str, replies: list[AIMessage]) -> ChatResult:
    return await respond(
        message, [], client=FakeClient(replies), retriever=FakeRetriever(), tools=[STOCK]
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
