"""OpenRouter (OpenAI-compatible API), used as the agent model's fallback when Groq rate-limits.

Built lazily like `GroqLLMClient`, so importing this is safe without an API key.
"""

from langchain_core.language_models import BaseChatModel

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self._chat: BaseChatModel | None = None

    @property
    def chat_model(self) -> BaseChatModel:
        if self._chat is None:
            from langchain_openai import ChatOpenAI

            kwargs = {}
            if self.reasoning_effort is not None:
                # OpenRouter's unified reasoning control; ignored by non-reasoning models.
                kwargs["extra_body"] = {"reasoning": {"effort": self.reasoning_effort}}
            self._chat = ChatOpenAI(
                model=self.model,
                api_key=self.api_key,
                base_url=OPENROUTER_BASE_URL,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **kwargs,
            )
        return self._chat
