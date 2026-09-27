"""The real LLM call, via LangChain's Groq chat model.

Nothing is constructed at import time, so importing this module is safe without
an API key. The client is built lazily on first ``complete()``.
"""

from seller_pulse.llm.base import Message


class GroqLLMClient:
    def __init__(self, *, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._chat = None

    def _get_chat(self):
        if self._chat is None:
            from langchain_groq import ChatGroq

            self._chat = ChatGroq(model=self.model, api_key=self.api_key)
        return self._chat

    def complete(self, *, system: str, messages: list[Message]) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        lc_messages = [SystemMessage(content=system)]
        for message in messages:
            cls = HumanMessage if message["role"] == "user" else AIMessage
            lc_messages.append(cls(content=message["content"]))

        response = self._get_chat().invoke(lc_messages)
        return response.content
