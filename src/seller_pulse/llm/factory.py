from seller_pulse.config import Settings
from seller_pulse.llm.base import LLMClient
from seller_pulse.llm.groq_client import GroqLLMClient


def get_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "groq":
        return GroqLLMClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r}; expected 'groq'."
    )


def get_router_client(settings: Settings, model: str | None = None) -> LLMClient:
    """The query classifier's model (rt-04): deterministic and cheap. `model` overrides
    `Settings.router_model` (the route eval compares candidates)."""
    if settings.llm_provider == "groq":
        return GroqLLMClient(
            api_key=settings.groq_api_key,
            model=model or settings.router_model,
            temperature=0,
            reasoning_effort="low",
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r}; expected 'groq'."
    )
