import logging

import pytest

from seller_pulse.cache import CacheStats, MemoryCache


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
