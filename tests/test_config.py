import pytest

from seller_pulse.config import (
    DEFAULT_CACHE_EMBED_MAX,
    DEFAULT_CACHE_TOOL_MAX,
    DEFAULT_CACHE_TOOL_TTL_S,
    load_settings,
)

CACHE_VARS = ("CACHING", "CACHE_EMBED_MAX", "CACHE_TOOL_MAX", "CACHE_TOOL_TTL_S")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    for name in CACHE_VARS:
        monkeypatch.delenv(name, raising=False)


def test_cache_defaults_when_unset():
    s = load_settings()
    assert s.caching is True
    assert s.cache_embed_max == DEFAULT_CACHE_EMBED_MAX
    assert s.cache_tool_max == DEFAULT_CACHE_TOOL_MAX
    assert s.cache_tool_ttl_s == DEFAULT_CACHE_TOOL_TTL_S


def test_cache_defaults_when_blank(monkeypatch):
    for name in CACHE_VARS:
        monkeypatch.setenv(name, "")
    assert load_settings().caching is True
    assert load_settings().cache_tool_max == DEFAULT_CACHE_TOOL_MAX


def test_caching_off(monkeypatch):
    monkeypatch.setenv("CACHING", "OFF")
    assert load_settings().caching is False


def test_bad_caching_raises(monkeypatch):
    monkeypatch.setenv("CACHING", "maybe")
    with pytest.raises(ValueError, match="CACHING"):
        load_settings()


def test_cache_knobs_honoured(monkeypatch):
    monkeypatch.setenv("CACHE_EMBED_MAX", "8")
    monkeypatch.setenv("CACHE_TOOL_MAX", "5")
    monkeypatch.setenv("CACHE_TOOL_TTL_S", "60")
    s = load_settings()
    assert (s.cache_embed_max, s.cache_tool_max, s.cache_tool_ttl_s) == (8, 5, 60)


@pytest.mark.parametrize("name", CACHE_VARS[1:])
@pytest.mark.parametrize("bad", ["0", "-3", "abc", "nan"])
def test_bad_cache_knob_raises(monkeypatch, name, bad):
    monkeypatch.setenv(name, bad)
    with pytest.raises(ValueError, match=name):
        load_settings()
