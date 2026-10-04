"""The real LLM, via LangChain's Groq chat model.

Nothing is constructed at import time, so importing this module is safe without
an API key. The model is built lazily on first ``chat_model`` access.
"""

from langchain_core.language_models import BaseChatModel


class GroqLLMClient:
    def __init__(self, *, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._chat: BaseChatModel | None = None

    @property
    def chat_model(self) -> BaseChatModel:
        if self._chat is None:
            from langchain_groq import ChatGroq

            self._chat = ChatGroq(model=self.model, api_key=self.api_key)
        return self._chat
