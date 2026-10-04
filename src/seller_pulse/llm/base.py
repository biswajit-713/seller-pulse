"""The seam between the app and whatever actually answers a question.

The client hands out a LangChain chat model; `agent.run_agent` binds tools to it and owns the
`Message` → LangChain translation.
"""

from typing import Literal, Protocol, TypedDict

from langchain_core.language_models import BaseChatModel


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class LLMClient(Protocol):
    @property
    def chat_model(self) -> BaseChatModel:
        """The underlying chat model, for `bind_tools`."""
        ...
