"""Placeholder for the real Anthropic call.

Nothing is constructed at import time, so importing this module is safe without
an API key. Filling this in later means building an ``anthropic.Anthropic``
client from ``api_key`` and calling ``messages.create`` with the arguments
``complete`` already receives.
"""

from seller_pulse.llm.base import Message


class AnthropicLLMClient:
    def __init__(self, *, api_key: str | None, model: str, max_tokens: int = 1024) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, *, system: str, messages: list[Message]) -> str:
        raise NotImplementedError(
            "The Anthropic integration is not wired up yet. "
            "Set LLM_PROVIDER=fake to use the stubbed client."
        )
