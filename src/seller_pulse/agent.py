"""The async tool loop: model → tool calls → tool results → model, until a plain answer.

Plain loop, no LangGraph. Async because MCP adapter tools are async-only; local
`StructuredTool`s support `ainvoke` too.

Tool failures (exception, timeout, unknown name) are fed back to the model as an error envelope rather
than raised — the model decides how to degrade. Every call, failed or not, is recorded in
`AgentResult.tool_calls` so the answer and the trace panel share one source of truth.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass

import groq
import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from seller_pulse.llm.base import Message

# A provider's 429 (Groq, or OpenRouter via the OpenAI SDK): the only error the fallback model covers.
RATE_LIMIT_ERRORS = (groq.RateLimitError, openai.RateLimitError)

# Wall-clock cap on one tool call. The MCP path spawns a server subprocess per call, so a hung
# server would otherwise hang the turn. Normal calls finish in a second or two.
TOOL_TIMEOUT_S = 15.0

FALLBACK_TEXT = (
    "I couldn't finish pulling the data for that question. "
    "Could you try asking again, perhaps more specifically?"
)


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    args: dict
    result: dict  # the envelope, or {"ok": False, "error": {"code": "TOOL_EXCEPTION", ...}}
    cached: bool = False
    latency_ms: int = 0


@dataclass(frozen=True)
class AgentResult:
    text: str
    tool_calls: list[ToolCallRecord]


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


_SKU_IN_TEXT = re.compile(r"sku[\s-]*(\d{4})", re.IGNORECASE)


def _skus_in(text: str) -> set[str]:
    return {f"SKU-{digits}" for digits in _SKU_IN_TEXT.findall(text)}


def _unconfirmed_sku(args: dict, confirmed: set[str]) -> dict | None:
    """Error envelope when a call passes a SKU that came from neither the conversation nor a tool.

    The context block carries SKUs from reviews; a model that copies one for a product the seller
    only named skips `find_listing` and may analyse the wrong listing. Prompt wording lowers that
    rate but cannot rule it out, so the loop does.
    """
    sku = args.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        return None
    # A malformed SKU is the tool's to reject (INVALID_SKU), not ours.
    if _skus_in(sku) <= confirmed:
        return None
    return _error(
        "UNCONFIRMED_SKU",
        f"{sku.strip()} was not given by the seller or returned by a tool. Call find_listing with the "
        "product name the seller used, then use a SKU from its matches.",
    )


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
        async with asyncio.timeout(TOOL_TIMEOUT_S) as deadline:
            return await tool.ainvoke(args)
    except Exception as exc:
        # The MCP adapter's task group re-raises a cancellation as an ExceptionGroup, so the
        # deadline, not the exception type, says whether this was a timeout.
        if isinstance(exc, TimeoutError) or deadline.expired():
            return _error("TIMEOUT", f"{name} did not return within {TOOL_TIMEOUT_S:g}s. No data was retrieved.")
        return _error("TOOL_EXCEPTION", f"{type(exc).__name__}: {exc}")


async def run_agent(
    model: BaseChatModel,
    *,
    system: str,
    messages: list[Message],
    tools: list[BaseTool],
    max_steps: int = 5,
    fallback: BaseChatModel | None = None,
    callbacks: list | None = None,
) -> AgentResult:
    """Run the tool loop for at most ``max_steps`` model calls. ``fallback`` answers any call
    that ``model`` rejects with a rate-limit error (429). ``callbacks`` (e.g. a tracing handler)
    are attached to every model call."""

    def bind(m: BaseChatModel):
        # No tools routed (rt-06): call the bare model — an empty `tools` array is not sent.
        return m.bind_tools(tools) if tools else m

    bound = bind(model)
    if fallback is not None:
        bound = bound.with_fallbacks([bind(fallback)], exceptions_to_handle=RATE_LIMIT_ERRORS)
    if callbacks:
        bound = bound.with_config(callbacks=callbacks)
    tools_by_name = {tool.name: tool for tool in tools}
    lc_messages = _to_langchain(system, messages)
    records: list[ToolCallRecord] = []
    # SKUs the seller or an earlier answer already named (history included), then any a tool returns.
    confirmed: set[str] = set().union(*(_skus_in(m["content"]) for m in messages)) if messages else set()

    for _ in range(max_steps):
        reply = await bound.ainvoke(lc_messages)
        if not reply.tool_calls:
            return AgentResult(text=reply.content, tool_calls=records)

        lc_messages.append(reply)
        for call in reply.tool_calls:
            started = time.perf_counter()
            result = _unconfirmed_sku(call["args"], confirmed) or await _run_tool(
                tools_by_name, call["name"], call["args"]
            )
            latency_ms = round((time.perf_counter() - started) * 1000)
            # Private flag from the cache wrapper: for the record only, never the model or guardrail.
            cached = bool(result.pop("_cache_hit", False))
            records.append(
                ToolCallRecord(
                    name=call["name"],
                    args=call["args"],
                    result=result,
                    cached=cached,
                    latency_ms=latency_ms,
                )
            )
            confirmed |= _skus_in(json.dumps(result))
            lc_messages.append(ToolMessage(json.dumps(result), tool_call_id=call["id"]))

    # The last reply asked for more tools, so its content is empty or a preamble
    # written before seeing results — not an answer.
    return AgentResult(text=FALLBACK_TEXT, tool_calls=records)
