import logging

import pytest
from langchain_core.tools import StructuredTool

from seller_pulse.cache import CacheStats, MemoryCache, cached_tools, tool_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_round_trip():
    cache = MemoryCache(max_entries=2, name="t")
    cache.set("a", {"x": 1})
    assert cache.get("a") == {"x": 1}


def test_miss_returns_none():
    assert MemoryCache(max_entries=2, name="t").get("nope") is None


def test_ttl_expiry_at_boundary_counts_as_expired():
    clock = FakeClock()
    cache = MemoryCache(max_entries=2, name="t", clock=clock)
    cache.set("a", 1, ttl_s=10)
    clock.now = 9.99
    assert cache.get("a") == 1
    clock.now = 10.0
    assert cache.get("a") is None
    assert cache.get("a") is None  # dropped, still a miss


def test_no_ttl_never_expires():
    clock = FakeClock()
    cache = MemoryCache(max_entries=2, name="t", clock=clock)
    cache.set("a", 1)
    clock.now = 1e9
    assert cache.get("a") == 1


def test_lru_eviction_order_and_get_refreshes():
    cache = MemoryCache(max_entries=2, name="t")
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # refresh a → b is now least recent
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_overwrite_does_not_evict():
    cache = MemoryCache(max_entries=2, name="t")
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("a", 3)
    assert cache.get("a") == 3
    assert cache.get("b") == 2


def test_evict_logs(caplog):
    cache = MemoryCache(max_entries=1, name="tools")
    cache.set("a", 1)
    with caplog.at_level(logging.INFO, logger="seller_pulse.cache"):
        cache.set("b", 2)
    assert "cache name=tools evict key=a" in caplog.text


def test_max_entries_below_one_raises():
    with pytest.raises(ValueError):
        MemoryCache(max_entries=0, name="t")


def test_stats_hit_rate():
    stats = CacheStats()
    assert stats.hit_rate == 0.0
    stats.record(True)
    stats.record(False)
    stats.record(True)
    assert stats.hit_rate == pytest.approx(2 / 3)


# --- tool cache (ca-04) ---


def _counting_tool(name: str, calls: list, result: dict):
    async def fn(period: str = "", sku: str = "") -> dict:
        calls.append((period, sku))
        return result

    return StructuredTool.from_function(coroutine=fn, name=name, description="fake")


def _wrap(tool, clock=None):
    cache = MemoryCache(max_entries=8, name="t", **({"clock": clock} if clock else {}))
    (wrapped,) = cached_tools([tool], cache, CacheStats(), ttl_s=10)
    return wrapped


async def test_repeat_call_hits_cache_and_flags_it():
    calls: list = []
    tool = _wrap(_counting_tool("get_sales_analytics", calls, {"ok": True, "data": {}}))
    first = await tool.ainvoke({"period": "last_week"})
    second = await tool.ainvoke({"period": "last_week"})
    assert len(calls) == 1
    assert "_cache_hit" not in first
    assert second["_cache_hit"] is True


async def test_equivalent_args_share_a_key():
    assert tool_key("get_sales_analytics", {"period": "Last Week"}) == tool_key(
        "get_sales_analytics", {"period": "last_week"}
    )
    assert tool_key("check_inventory_status", {"sku": " sku-1001"}) == tool_key(
        "check_inventory_status", {"sku": "SKU-1001"}
    )


async def test_error_envelope_not_stored():
    calls: list = []
    tool = _wrap(_counting_tool("check_inventory_status", calls, {"ok": False, "error": {}}))
    await tool.ainvoke({"sku": "SKU-9999"})
    await tool.ainvoke({"sku": "SKU-9999"})
    assert len(calls) == 2


async def test_ttl_expiry_reinvokes():
    now = [0.0]
    calls: list = []
    tool = _wrap(
        _counting_tool("get_sales_analytics", calls, {"ok": True, "data": {}}),
        clock=lambda: now[0],
    )
    await tool.ainvoke({"period": "today"})
    now[0] = 11
    await tool.ainvoke({"period": "today"})
    assert len(calls) == 2


async def test_other_tools_pass_through_unwrapped():
    memory = _counting_tool("save_preference", [], {"ok": True})
    (out,) = cached_tools([memory], MemoryCache(max_entries=2, name="t"), CacheStats(), ttl_s=1)
    assert out is memory
