from seller_pulse.config import Settings
from seller_pulse.llm.anthropic_client import AnthropicLLMClient
from seller_pulse.llm.base import LLMClient
from seller_pulse.llm.fake import FakeLLMClient


def get_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLMClient()
    if settings.llm_provider == "anthropic":
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r}; expected 'fake' or 'anthropic'."
    )
