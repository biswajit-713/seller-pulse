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
