"""The one place the request pipeline is sequenced: sanitize, route + retrieve, run the tool loop.

Routing (`plan/rt-06-chat-wiring.md`) picks the prompt modules and the tools bound; retrieval
is unconditional and runs concurrently with the classifier, so routing costs about
max(classifier, retrieval) rather than their sum.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from seller_pulse.agent import ToolCallRecord, run_agent
from seller_pulse.llm.base import LLMClient, Message
from seller_pulse.prompts import build_system_prompt
from seller_pulse.rag.context import render_context
from seller_pulse.rag.retrieval import Retriever
from seller_pulse.router import Route, RouteDecision, tools_for
from seller_pulse.sanitize import sanitize

logger = logging.getLogger(__name__)

EMPTY_INPUT_REPLY = "Type a question about your seller data and I'll take a look."

# `router.classify_query` with its model bound (`functools.partial`); a callable so tests can
# fake it without a chat model. Must not raise — `classify_query` fails open itself.
Classifier = Callable[[str, list[Message]], Awaitable[RouteDecision]]


@dataclass(frozen=True)
class ChatResult:
    text: str
    trace: list[ToolCallRecord]  # w2-14 adds recalled preferences
    routes: frozenset[Route] = frozenset()
    route_fallback: bool = False  # the classifier failed open to all routes


def to_messages(history: list[dict[str, Any]] | None) -> list[Message]:
    """Turn Gradio's ``type="messages"`` history into Anthropic-shaped messages.

    Gradio can emit entries the API will not accept — tool/metadata rows, or file
    payloads whose content is a tuple rather than a string — so anything that is
    not a plain user/assistant text turn is dropped.
    """
    messages: list[Message] = []
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        if not content.strip():
            continue
        messages.append({"role": role, "content": content})
    return messages


def _log_tool_call(record: ToolCallRecord) -> None:
    ok = record.result.get("ok")
    if ok:
        logger.info("tool %s args=%s ok=True", record.name, record.args)
    else:
        code = (record.result.get("error") or {}).get("code")
        logger.info("tool %s args=%s ok=False code=%s", record.name, record.args, code)


async def respond(
    message: str,
    history: list[dict[str, Any]] | None,
    *,
    client: LLMClient,
    retriever: Retriever,
    tools: list[BaseTool],
    classify: Classifier,
) -> ChatResult:
    clean = sanitize(message)
    if not clean:
        return ChatResult(text=EMPTY_INPUT_REPLY, trace=[])

    previous = to_messages(history)
    decision, retrieved = await asyncio.gather(
        classify(clean, previous), asyncio.to_thread(retriever.retrieve, clean)
    )
    routed_tools = tools_for(decision.routes, tools)
    logger.info(
        "routes=%s fallback=%s classify_ms=%d tools=%s",
        [r.value for r in sorted(decision.routes)],
        decision.fallback,
        decision.latency_ms,
        [t.name for t in routed_tools],
    )

    messages: list[Message] = [*previous, {"role": "user", "content": clean}]
    system = f"{build_system_prompt(decision.routes)}\n\n{render_context(retrieved)}"
    # Tool results go back to the model unsanitised until Week 3's guardrails.
    result = await run_agent(client.chat_model, system=system, messages=messages, tools=routed_tools)
    for record in result.tool_calls:
        _log_tool_call(record)
    return ChatResult(
        text=result.text,
        trace=result.tool_calls,
        routes=decision.routes,
        route_fallback=decision.fallback,
    )
