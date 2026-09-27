from seller_pulse.config import Settings
from seller_pulse.llm.base import LLMClient
from seller_pulse.llm.groq_client import GroqLLMClient


def get_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "groq":
        return GroqLLMClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r}; expected 'groq'."
    )
