import langchain_groq

from seller_pulse.config import DEFAULT_JUDGE_MODEL, load_settings
from seller_pulse.llm.groq_client import GroqLLMClient


class FakeChatGroq:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_temperature_is_passed_when_set(monkeypatch):
    monkeypatch.setattr(langchain_groq, "ChatGroq", FakeChatGroq)
    client = GroqLLMClient(api_key="k", model="m", temperature=0)
    assert client.chat_model.kwargs == {"model": "m", "api_key": "k", "temperature": 0}


def test_temperature_omitted_by_default(monkeypatch):
    monkeypatch.setattr(langchain_groq, "ChatGroq", FakeChatGroq)
    client = GroqLLMClient(api_key="k", model="m")
    assert "temperature" not in client.chat_model.kwargs


def test_judge_model_defaults(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    assert load_settings().judge_model == DEFAULT_JUDGE_MODEL


def test_judge_model_honours_env(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("JUDGE_MODEL", "some/judge")
    assert load_settings().judge_model == "some/judge"


def test_fallback_client_needs_openrouter_key(monkeypatch):
    from seller_pulse.llm import get_fallback_client

    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert get_fallback_client(load_settings()) is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    client = get_fallback_client(load_settings())
    assert client.model == "openai/gpt-oss-120b" and client.api_key == "or-key"


def test_agent_client_caps_tokens_and_retries(monkeypatch):
    from seller_pulse.llm import get_client

    monkeypatch.setattr(langchain_groq, "ChatGroq", FakeChatGroq)
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    kwargs = get_client(load_settings()).chat_model.kwargs
    assert kwargs["reasoning_effort"] == "low" and kwargs["max_tokens"] == 1500
    assert kwargs["max_retries"] == 4
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert get_client(load_settings()).chat_model.kwargs["max_retries"] == 1


def test_openrouter_primary_provider(monkeypatch):
    import pytest

    from seller_pulse.llm import get_client, get_fallback_client, get_router_client

    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        load_settings()
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("ROUTER_MODEL", raising=False)
    settings = load_settings()
    agent, router = get_client(settings), get_router_client(settings)
    assert (agent.model, agent.api_key, agent.max_tokens) == ("openai/gpt-oss-120b", "or-key", 1500)
    assert router.model == "openai/gpt-oss-20b" and router.temperature == 0
    assert get_fallback_client(settings) is None


def test_openrouter_judge_and_agent_model(monkeypatch):
    from seller_pulse.llm import get_judge_client

    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    settings = load_settings()
    judge = get_judge_client(settings)
    assert judge.model == "qwen/qwen3-32b" and judge.api_key == "or-key"
    assert settings.agent_model == "openai/gpt-oss-120b"
