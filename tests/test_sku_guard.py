from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from seller_pulse.agent import run_agent


class Scripted:
    """Replies in order; records the tool messages it was shown."""

    def __init__(self, replies):
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self.replies.pop(0)


def _call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _find(name: str) -> dict:
    return {"ok": True, "data": {"matches": [{"sku": "SKU-1001", "title": "Boho Wall Hanging - Macrame"}]}}


def _sales(period: str, sku: str | None = None) -> dict:
    return {"ok": True, "data": {"sku": sku}}


FIND = StructuredTool.from_function(func=_find, name="find_listing", description="find")
SALES = StructuredTool.from_function(func=_sales, name="get_sales_analytics", description="sales")


async def _run(replies, query):
    return await run_agent(
        Scripted(replies), system="s", messages=[{"role": "user", "content": query}], tools=[FIND, SALES]
    )


async def test_sku_not_from_seller_or_tool_is_rejected():
    result = await _run(
        [_call("get_sales_analytics", {"period": "last_30_days", "sku": "SKU-1001"}, "1"), AIMessage(content="ok")],
        "Why is my Boho Wall Hanging underperforming?",
    )
    assert result.tool_calls[0].result["error"]["code"] == "UNCONFIRMED_SKU"


async def test_sku_returned_by_find_listing_is_accepted():
    result = await _run(
        [
            _call("find_listing", {"name": "Boho Wall Hanging"}, "1"),
            _call("get_sales_analytics", {"period": "last_30_days", "sku": "SKU-1001"}, "2"),
            AIMessage(content="ok"),
        ],
        "Why is my Boho Wall Hanging underperforming?",
    )
    assert [r.result["ok"] for r in result.tool_calls] == [True, True]


async def test_sku_typed_by_seller_is_accepted_any_case():
    result = await _run(
        [_call("get_sales_analytics", {"period": "last_30_days", "sku": "SKU-1001"}, "1"), AIMessage(content="ok")],
        "how is sku-1001 doing",
    )
    assert result.tool_calls[0].result["ok"] is True


async def test_call_without_sku_is_never_blocked():
    result = await _run(
        [_call("get_sales_analytics", {"period": "last_30_days"}, "1"), AIMessage(content="ok")],
        "How are sales?",
    )
    assert result.tool_calls[0].result["ok"] is True
