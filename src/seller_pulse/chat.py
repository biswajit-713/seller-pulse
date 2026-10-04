"""The one place the request pipeline is sequenced: sanitize, bundle, run the tool loop."""

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from seller_pulse.agent import ToolCallRecord, run_agent
from seller_pulse.llm.base import LLMClient, Message
from seller_pulse.prompts import SYSTEM_PROMPT
from seller_pulse.rag.context import render_context
from seller_pulse.rag.retrieval import Retriever
from seller_pulse.sanitize import sanitize

logger = logging.getLogger(__name__)

EMPTY_INPUT_REPLY = "Type a question about your seller data and I'll take a look."


@dataclass(frozen=True)
class ChatResult:
    text: str
    trace: list[ToolCallRecord]  # w2-14 adds recalled preferences


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
) -> ChatResult:
    clean = sanitize(message)
    if not clean:
        return ChatResult(text=EMPTY_INPUT_REPLY, trace=[])

    messages: list[Message] = to_messages(history)
    messages.append({"role": "user", "content": clean})

    system = f"{SYSTEM_PROMPT}\n\n{render_context(retriever.retrieve(clean))}"
    # Tool results go back to the model unsanitised until Week 3's guardrails.
    result = await run_agent(client.chat_model, system=system, messages=messages, tools=tools)
    for record in result.tool_calls:
        _log_tool_call(record)
    return ChatResult(text=result.text, trace=result.tool_calls)
