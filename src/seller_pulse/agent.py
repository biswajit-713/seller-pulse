"""The async tool loop: model → tool calls → tool results → model, until a plain answer.

Plain loop, no LangGraph. Async because MCP adapter tools are async-only; local
`StructuredTool`s support `ainvoke` too.

Tool failures (exception, unknown name) are fed back to the model as an error envelope rather
than raised — the model decides how to degrade. Every call, failed or not, is recorded in
`AgentResult.tool_calls` so the answer and the trace panel share one source of truth.
"""

import json
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from seller_pulse.llm.base import Message

FALLBACK_TEXT = (
    "I couldn't finish pulling the data for that question. "
    "Could you try asking again, perhaps more specifically?"
)


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    args: dict
    result: dict  # the envelope, or {"ok": False, "error": {"code": "TOOL_EXCEPTION", ...}}


@dataclass(frozen=True)
class AgentResult:
    text: str
    tool_calls: list[ToolCallRecord]


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _to_langchain(system: str, messages: list[Message]) -> list[BaseMessage]:
    lc_messages: list[BaseMessage] = [SystemMessage(content=system)]
    for message in messages:
        cls = HumanMessage if message["role"] == "user" else AIMessage
        lc_messages.append(cls(content=message["content"]))
    return lc_messages


async def _run_tool(tools_by_name: dict[str, BaseTool], name: str, args: dict) -> dict:
    tool = tools_by_name.get(name)
    if tool is None:
        return _error("UNKNOWN_TOOL", f"No tool named {name!r}.")
    try:
        return await tool.ainvoke(args)
    except Exception as exc:
        return _error("TOOL_EXCEPTION", f"{type(exc).__name__}: {exc}")


async def run_agent(
    model: BaseChatModel,
    *,
    system: str,
    messages: list[Message],
    tools: list[BaseTool],
    max_steps: int = 5,
) -> AgentResult:
    """Run the tool loop for at most ``max_steps`` model calls."""
    # No tools routed (rt-06): call the bare model — an empty `tools` array is not sent.
    bound = model.bind_tools(tools) if tools else model
    tools_by_name = {tool.name: tool for tool in tools}
    lc_messages = _to_langchain(system, messages)
    records: list[ToolCallRecord] = []

    for _ in range(max_steps):
        reply = await bound.ainvoke(lc_messages)
        if not reply.tool_calls:
            return AgentResult(text=reply.content, tool_calls=records)

        lc_messages.append(reply)
        for call in reply.tool_calls:
            result = await _run_tool(tools_by_name, call["name"], call["args"])
            records.append(ToolCallRecord(name=call["name"], args=call["args"], result=result))
            lc_messages.append(ToolMessage(json.dumps(result), tool_call_id=call["id"]))

    # The last reply asked for more tools, so its content is empty or a preamble
    # written before seeing results — not an answer.
    return AgentResult(text=FALLBACK_TEXT, tool_calls=records)
