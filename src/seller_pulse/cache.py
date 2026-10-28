"""The cache contract: one small seam so a disk backend can replace the in-memory one.

Callers depend on `Cache` only. Values must be JSON-compatible (so a sqlite/disk backend can
store them) — documented, not enforced at runtime. `None` is never a stored value, so `get`
returning `None` always means a miss.

The API is sync on purpose: the async tool wrapper calls it directly, and a future sqlite
backend is fast enough not to need `await`.

No thread lock: Gradio runs handlers on one event loop, and `retrieve` runs in
`asyncio.to_thread`. Single `OrderedDict` operations are atomic under CPython's GIL, so the
worst case is two threads missing on the same key and computing the same value twice —
duplicate work, never corruption. `MemoryCache.get` uses `pop` (not check-then-delete) to
stay safe under that interleaving.
"""

import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool

from seller_pulse.inventory import normalise_sku
from seller_pulse.sales import normalise_period

logger = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_s: float | None = None) -> None: ...


class MemoryCache:
    """In-process LRU with optional per-entry TTL."""

    def __init__(
        self,
        *,
        max_entries: int,
        name: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self._max_entries = max_entries
        self._name = name
        self._clock = clock
        # key -> (value, expires_at or None)
        self._data: OrderedDict[str, tuple[Any, float | None]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        entry = self._data.pop(key, None)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and self._clock() >= expires_at:
            return None
        self._data[key] = entry  # re-insert at the end: most recently used
        return value

    def set(self, key: str, value: Any, ttl_s: float | None = None) -> None:
        expires_at = None if ttl_s is None else self._clock() + ttl_s
        self._data.pop(key, None)
        self._data[key] = (value, expires_at)
        while len(self._data) > self._max_entries:
            evicted, _ = self._data.popitem(last=False)
            logger.info("cache name=%s evict key=%s", self._name, evicted)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0

    def record(self, hit: bool) -> None:
        if hit:
            self.hits += 1
        else:
            self.misses += 1

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


# Read-only tools only; memory tools have side effects and are never cached.
CACHED_TOOLS = frozenset({"get_sales_analytics", "check_inventory_status", "get_top_products", "get_review_summary"})


def tool_key(name: str, args: dict) -> str:
    """Tool name + args normalised the way the tools themselves do, so equivalents share a key."""
    normalised = dict(args)
    if "period" in normalised:
        normalised["period"] = normalise_period(normalised["period"])
    if "sku" in normalised:
        normalised["sku"] = normalise_sku(normalised["sku"])
    return f"{name}:{json.dumps(normalised, sort_keys=True)}"


def _cached_tool(tool: BaseTool, cache: Cache, stats: CacheStats, ttl_s: float) -> BaseTool:
    async def call(**kwargs) -> dict:
        key = tool_key(tool.name, kwargs)
        envelope = cache.get(key)
        stats.record(envelope is not None)
        if envelope is not None:
            logger.info("cache tool=%s hit key=%s", tool.name, key)
            return {**envelope, "_cache_hit": True}
        logger.info("cache tool=%s miss key=%s", tool.name, key)
        envelope = await tool.ainvoke(kwargs)
        if envelope.get("ok") is True:
            cache.set(key, envelope, ttl_s)
        return envelope

    return StructuredTool.from_function(
        coroutine=call, name=tool.name, description=tool.description, args_schema=tool.args_schema
    )


def cached_tools(
    tools: list[BaseTool], cache: Cache, stats: CacheStats, *, ttl_s: float
) -> list[BaseTool]:
    """`tools` with the read-only analytics tools served from `cache` on repeat calls."""
    return [
        _cached_tool(t, cache, stats, ttl_s) if t.name in CACHED_TOOLS else t for t in tools
    ]
