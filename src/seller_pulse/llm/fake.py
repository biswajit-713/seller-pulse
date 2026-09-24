"""A stand-in for the real model, used until the Anthropic call is wired up.

The reply echoes back what the pipeline actually carried (turn count, the last
user message, the size of the system prompt) so a glance at the UI confirms
sanitization and history assembly worked. Deterministic on purpose: no
randomness, no artificial delay.
"""

from seller_pulse.llm.base import Message


class FakeLLMClient:
    def complete(self, *, system: str, messages: list[Message]) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        return (
            "[stubbed reply — no model was called]\n\n"
            f"You asked: {last_user}\n\n"
            f"Turns received: {len(messages)}\n"
            f"System prompt attached: {len(system)} chars"
        )
