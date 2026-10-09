from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from seller_pulse.agent import FALLBACK_TEXT, ToolCallRecord, run_agent


class ScriptedChatModel:
    """Returns scripted AIMessages in order. GenericFakeChatModel can't bind_tools."""

    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.seen: list[list] = []  # the message list passed to each ainvoke

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def _call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id}


def _tool_reply(*calls: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


def _echo(sku: str) -> dict:
    return {"ok": True, "data": {"sku": sku}}


def _boom(sku: str) -> dict:
    raise RuntimeError("disk on fire")


ECHO = StructuredTool.from_function(func=_echo, name="echo", description="Echo a SKU.")
BOOM = StructuredTool.from_function(func=_boom, name="boom", description="Always fails.")

HISTORY = [{"role": "user", "content": "How is SKU-1001 doing?"}]


async def _run(replies, tools=(ECHO, BOOM), **kwargs):
    model = ScriptedChatModel(replies)
    result = await run_agent(model, system="sys", messages=HISTORY, tools=list(tools), **kwargs)
    return model, result


async def test_no_tool_call():
    _, result = await _run([AIMessage(content="Hello!")])
    assert result.text == "Hello!"
    assert result.tool_calls == []


async def test_one_call_then_answer():
    model, result = await _run([
        _tool_reply(_call("echo", {"sku": "SKU-1001"}, "c1")),
        AIMessage(content="Done."),
    ])
    assert result.text == "Done."
    assert result.tool_calls == [
        ToolCallRecord(name="echo", args={"sku": "SKU-1001"}, result=_echo("SKU-1001"))
    ]
    # The tool result reaches the model on the next step, tied to its call id.
    tool_message = model.seen[1][-1]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == "c1"


async def test_two_calls_in_one_turn():
    model, result = await _run([
        _tool_reply(_call("echo", {"sku": "SKU-1"}, "c1"), _call("echo", {"sku": "SKU-2"}, "c2")),
        AIMessage(content="Both checked."),
    ])
    assert [r.args["sku"] for r in result.tool_calls] == ["SKU-1", "SKU-2"]
    assert [m.tool_call_id for m in model.seen[1][-2:]] == ["c1", "c2"]


async def test_tool_exception_is_recorded_and_loop_continues():
    _, result = await _run([
        _tool_reply(_call("boom", {"sku": "SKU-1"}, "c1")),
        AIMessage(content="Sorry, that lookup failed."),
    ])
    assert result.text == "Sorry, that lookup failed."
    assert result.tool_calls[0].result["ok"] is False
    assert result.tool_calls[0].result["error"]["code"] == "TOOL_EXCEPTION"


async def test_unknown_tool():
    _, result = await _run([
        _tool_reply(_call("nope", {}, "c1")),
        AIMessage(content="ok"),
    ])
    assert result.tool_calls[0].result["error"]["code"] == "UNKNOWN_TOOL"


async def test_stops_at_max_steps_with_fallback():
    replies = [_tool_reply(_call("echo", {"sku": f"SKU-{i}"}, f"c{i}")) for i in range(3)]
    model, result = await _run(replies, max_steps=3)
    assert result.text == FALLBACK_TEXT
    assert len(result.tool_calls) == 3
    assert len(model.seen) == 3


async def test_no_tools_skips_bind_tools():
    class Unbindable(ScriptedChatModel):
        def bind_tools(self, tools):
            raise AssertionError("bind_tools called with no tools")

    model = Unbindable([AIMessage(content="Plain answer.")])
    result = await run_agent(model, system="sys", messages=HISTORY, tools=[])
    assert result.text == "Plain answer."
    assert len(model.seen) == 1
