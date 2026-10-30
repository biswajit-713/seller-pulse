from seller_pulse.config import Settings
from seller_pulse.llm.base import LLMClient
from seller_pulse.llm.groq_client import GroqLLMClient
from seller_pulse.llm.openrouter_client import OpenRouterLLMClient

# Output cap per agent call: Groq counts it toward TPM, and answers are short.
AGENT_MAX_TOKENS = 1500
# With a fallback, give up on Groq fast; without one, wait out its retry-after.
RETRIES_WITH_FALLBACK = 1
RETRIES_WITHOUT_FALLBACK = 4


def get_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "groq":
        return GroqLLMClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0,
            # gpt-oss reasoning tokens count toward Groq limits; other models reject the param.
            reasoning_effort="low" if "gpt-oss" in settings.groq_model else None,
            max_tokens=AGENT_MAX_TOKENS,
            max_retries=RETRIES_WITH_FALLBACK
            if settings.openrouter_api_key
            else RETRIES_WITHOUT_FALLBACK,
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


def get_fallback_client(settings: Settings) -> LLMClient | None:
    """The agent model's 429 fallback (`agent.run_agent`): OpenRouter when a key is set."""
    if settings.openrouter_api_key:
        return OpenRouterLLMClient(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            temperature=0,
            max_tokens=AGENT_MAX_TOKENS,
        )
    return None
