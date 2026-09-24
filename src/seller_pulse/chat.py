"""The one place the request pipeline is sequenced: sanitize, bundle, send."""

from typing import Any

from seller_pulse.llm.base import LLMClient, Message
from seller_pulse.prompts import SYSTEM_PROMPT
from seller_pulse.sanitize import sanitize

EMPTY_INPUT_REPLY = "Type a question about your seller data and I'll take a look."


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


def respond(message: str, history: list[dict[str, Any]] | None, client: LLMClient) -> str:
    clean = sanitize(message)
    if not clean:
        return EMPTY_INPUT_REPLY

    messages: list[Message] = to_messages(history)
    messages.append({"role": "user", "content": clean})

    return client.complete(system=SYSTEM_PROMPT, messages=messages)
