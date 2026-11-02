import sys

import pytest

from seller_pulse.config import load_settings
from seller_pulse.tracing import NO_TRACE, Tracing, build_tracing

KEYS = ("TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)


def test_off_without_keys_and_never_imports_langfuse():
    sys.modules.pop("langfuse", None)
    tracing = build_tracing(load_settings())
    assert not tracing.enabled
    with tracing.turn() as t:
        assert t is NO_TRACE
    tracing.flush()
    assert "langfuse" not in sys.modules


def test_off_when_flag_off_even_with_keys(monkeypatch):
    monkeypatch.setenv("TRACING", "off")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    assert not build_tracing(load_settings()).enabled


def test_one_key_is_not_enough(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    assert not load_settings().tracing_active


def test_blank_host_is_none(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "")
    assert load_settings().langfuse_host is None


class BrokenClient:
    def create_trace_id(self):
        raise RuntimeError("langfuse down")

    def flush(self):
        raise RuntimeError("langfuse down")


def test_client_errors_are_swallowed_and_logged(caplog):
    tracing = Tracing(BrokenClient())
    with tracing.turn() as t:
        assert t is NO_TRACE
    tracing.flush()
    assert "could not start trace" in caplog.text
    assert "flush failed" in caplog.text


def test_body_exceptions_propagate():
    with pytest.raises(ValueError):
        with Tracing().turn():
            raise ValueError("boom")
