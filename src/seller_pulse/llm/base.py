"""The seam between the app and whatever actually answers a question.

The signature deliberately mirrors ``anthropic.Anthropic().messages.create``:
a separate ``system`` prompt plus an alternating ``messages`` list. Swapping the
fake client for the real one is then a pass-through, not a translation.
"""

from typing import Literal, Protocol, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class LLMClient(Protocol):
    def complete(self, *, system: str, messages: list[Message]) -> str:
        """Return the assistant's reply to the final message in ``messages``."""
        ...
