# Caching

Two things are cached, in the app only: **query embeddings** and **analytics tool results**.
The model still writes every answer and the guardrail still checks it. Code: `cache.py`
(contract, `MemoryCache`, `CacheStats`, `cached_tools`), `rag/store.py:cached_embedder`,
wiring in `app.py`. Task thread: `plan/caching/`.

## What is cached

| | Embeddings | Tool results |
|---|---|---|
| Where | `rag/store.py:cached_embedder`, passed to the review/policy stores as `query_embeddings=` | `cache.cached_tools`, wrapping the tool list after `load_mcp_tools` |
| Key | exact sanitised query text | tool name + args normalised as the tool does (`normalise_period`, `normalise_sku`), so equivalent calls share a key |
| TTL | none (text + model fix the vector) | `CACHE_TOOL_TTL_S` (default 300 s) |
| Stored | `list[float]` | `ok=True` envelopes only; errors are never cached |
| Tools | – | `get_sales_analytics`, `check_inventory_status` only. Memory tools have side effects and are never cached |

A hit skips the work: the embedding call, or the MCP server subprocess spawn (~0.4–0.7 s per
call). `retrieve` embeds one question 2–3 times per turn (review, rating, policy search), so a
single turn already hits the embedding cache.

A tool hit returns a copy of the envelope with a private `_cache_hit: True`. `run_agent` pops it
into `ToolCallRecord.cached` before the result reaches the model, trace or guardrail, so the
model never sees it. The trace panel shows "(cached)" on that line.

**App only.** `app.py` is the sole caller that enables caching; tests, the agent eval and the
retrieval eval stay uncached so their baselines are comparable and order-independent.

## The `Cache` protocol, and swapping the backend

```python
class Cache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_s: float | None = None) -> None: ...
```

Sync on purpose. `None` is never stored, so `get` returning `None` is always a miss. Values must
be JSON-compatible (envelope dicts, `list[float]`) so a disk backend needs no serialisation
change. `MemoryCache` is an in-process LRU (`max_entries`, per-entry TTL, injectable clock) that
logs `cache name=… evict key=…`.

To add a disk backend: implement the two methods (sqlite is fast enough to stay sync), then
construct it in `app.py` in place of `MemoryCache`. Nothing else changes. Hit/miss counters live
in a `CacheStats` held by each call site, not in the protocol.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CACHING` | `on` | `off` disables both caches (use for before/after comparisons) |
| `CACHE_EMBED_MAX` | 1024 | embedding entries |
| `CACHE_TOOL_MAX` | 256 | tool-result entries |
| `CACHE_TOOL_TTL_S` | 300 | tool-result TTL, seconds |

Blank means the code default; zero or negative is rejected at load. For a demo where eviction and
expiry show up in the log, use `8 / 5 / 60` (`CACHE_EMBED_MAX` / `CACHE_TOOL_MAX` /
`CACHE_TOOL_TTL_S`; see `.env.example`).

## Why not cache the whole answer

It would be the biggest speed-up, and it is the only option where a hit can be *wrong*:

- **Follow-ups.** "And the week before?" means different things in different conversations.
- **Changed preferences.** Tone or restock threshold change the right answer.
- **Skipped writes.** Replaying a `save_preference` turn skips the write and falsely confirms it.
- **Stale figures.** A cached answer outlives the tool TTL its numbers came from.
- **Empty trace.** The panel would show nothing unless the whole `ChatResult` is stored.

It can be added later as a separate layer in `respond` over the same `Cache` protocol, without
touching these two caches, if: the key is (sanitised message, history, preferences snapshot);
turns that called a memory tool are never stored; TTL ≤ `CACHE_TOOL_TTL_S`; and `ChatResult`
gains a JSON round-trip.

A semantic (nearest-neighbour) variant is riskier still: "sales last week" and "sales this week"
embed almost identically, so it would also have to compare the tool args.

## Measured results

`uv run python -m seller_pulse.evals.cache_live --json evals/reports/cache_live.json`, run
2026-10-23 on `dee65eb` (+ the untracked script), Groq live, code-default cache sizes, 15 s pace.
Each question is asked twice, each as a fresh first turn, so the repeat differs only in cache
state.

| Question | Ask | turn_ms | Tool calls |
|---|---|---|---|
| SQ-01 | 1st | 5009 | get_sales_analytics 406 ms miss |
| SQ-01 | 2nd | 3557 | get_sales_analytics 0 ms hit |
| SKU-1001 | 1st | 5569 | check_inventory_status 703 ms miss |
| SKU-1001 | 2nd | 3641 | check_inventory_status 0 ms hit |
| LAST-MONTH | 1st | 5680 | get_sales_analytics 588 ms miss |
| LAST-MONTH | 2nd | 13963 | get_sales_analytics 0 ms hit |
| SQ-06 | 1st | 4029 | – |
| SQ-06 | 2nd | 9702 | – |

| | Median turn | Median tool call |
|---|---|---|
| First ask | 5289 ms | 588 ms |
| Repeat | 6672 ms | 0 ms |

| Cache | Hits | Misses | Hit rate |
|---|---|---|---|
| Embedding | 12 | 4 | 75.0% |
| Tool result | 3 | 3 | 50.0% |

How to read it:

- **Tool `latency_ms` is the clean signal.** A hit costs ~0 ms against 400–700 ms for the
  subprocess spawn it skips, on every repeated question.
- **`turn_ms` is noisy and does not show the gain in this run.** It includes the classifier and
  agent model calls, which are not cached and vary a lot (the LAST-MONTH repeat took 13.9 s and
  SQ-06's 9.7 s with no tool at all). The repeat median (6672 ms) is *worse* than the first
  (5289 ms) only because of those model calls. The two clean pairs (SQ-01, SKU-1001) are ~1.4–1.9 s
  faster on the repeat, in line with the saved spawn plus model variance. Don't quote the turn
  medians as a speed-up.
- **The policy question calls no tool**, so SQ-06 shows the embedding cache alone: no visible
  turn-level effect, since the Chroma lookup was already milliseconds.
- **Hit rates are low by construction**: four questions asked twice, so the ceiling is 50% for
  tools. Embeddings hit more because one turn embeds the same text several times.

### Miss → hit in the log

From a second run (same sequence, `INFO` logging on `seller_pulse.*`):

```
seller_pulse.rag.store cache embed miss len=35
seller_pulse.rag.store cache embed hit len=35
seller_pulse.cache cache tool=get_sales_analytics miss key=get_sales_analytics:{"period": "last_week"}
seller_pulse.chat tool get_sales_analytics args={'period': 'last_week'} ok=True ms=560 cached=False
  …
seller_pulse.cache cache tool=get_sales_analytics hit key=get_sales_analytics:{"period": "last_week"}
  …
seller_pulse.cache cache tool=get_sales_analytics hit key=get_sales_analytics:{"period": "last_month"}
seller_pulse.chat tool get_sales_analytics args={'period': 'last_month'} ok=True ms=1 cached=True
```

The first embed miss/hit pair is one turn embedding the same question twice.

## Known limits

- **In-process only.** Caches reset on restart, and are per process.
- **The first call still pays the MCP spawn.** A persistent MCP session is the separate follow-up
  (`mcp_tools.py`) and would cut the miss cost too.
- **Not measured:** eviction and TTL expiry with the demo values (`8 / 5 / 60`); covered by unit
  tests with a fake clock only.
