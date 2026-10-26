"""The live cache measurement (ca-06, `docs/tasks.md` #23): what the caches buy, from one command.

    uv run python -m seller_pulse.evals.cache_live [--pace S] [--json PATH]

Live, never a pytest test: it calls Groq (~8 agent + 8 classifier calls). The pipeline is built as
`app.build_app` builds it (stdio MCP tools, router, retriever, `store=None` so no recall) with
both caches at the code defaults, passed explicitly so `.env` cannot change the result. Each
question in `SEQUENCE` is asked twice back to back, each time as a fresh first turn (empty
history), so the repeat differs from the first ask only in cache state.

Tool `latency_ms` is the clean signal (the subprocess spawn a hit skips); `turn_ms` is the
user-visible one but includes model calls, which vary run to run. The policy question calls no
tool, so it shows the embedding cache alone. `summarise` and `render_table` are pure and
pytest-tested with fakes. Exit codes mirror `agent_eval`: 0 done, 2 the run could not start.
"""

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from seller_pulse.cache import CacheStats, MemoryCache, cached_tools
from seller_pulse.chat import ChatResult, respond
from seller_pulse.config import (
    DEFAULT_CACHE_EMBED_MAX,
    DEFAULT_CACHE_TOOL_MAX,
    DEFAULT_CACHE_TOOL_TTL_S,
    load_settings,
)
from seller_pulse.evals.agent_eval import _fail
from seller_pulse.llm import get_client
from seller_pulse.mcp_tools import load_mcp_tools
from seller_pulse.rag.retrieval import build_retriever
from seller_pulse.router import build_classifier

PACE_S = 15.0  # one turn is an agent + a classifier call; spaced to stay under Groq's 8k TPM

# (id, message). SQ ids are `queries.jsonl` ids; the two without one are variants of the same
# tools: a second period for sales, and an SKU stock check.
SEQUENCE: tuple[tuple[str, str], ...] = (
    ("SQ-01", "How did my sales perform last week?"),
    ("SKU-1001", "How many units of SKU-1001 are left in stock?"),
    ("LAST-MONTH", "How did my sales perform last month?"),
    ("SQ-06", "Can you offer buyers a free gift for leaving a 5-star review?"),
)

Ask = Callable[[str], Awaitable[ChatResult]]


@dataclass(frozen=True)
class ToolTiming:
    name: str
    latency_ms: int
    cached: bool


@dataclass(frozen=True)
class Row:
    question_id: str
    attempt: int  # 1 = first ask, 2 = repeat
    turn_ms: int
    tools: tuple[ToolTiming, ...]


async def run_sequence(
    ask: Ask, sequence: tuple[tuple[str, str], ...] = SEQUENCE, pace_s: float = 0
) -> list[Row]:
    """Each question twice, back to back, timed around `ask` (the whole `respond` turn)."""
    rows: list[Row] = []
    for question_id, message in sequence:
        for attempt in (1, 2):
            if rows and pace_s:
                await asyncio.sleep(pace_s)  # outside the timed call
            started = time.perf_counter()
            result = await ask(message)
            turn_ms = round((time.perf_counter() - started) * 1000)
            tools = tuple(ToolTiming(t.name, t.latency_ms, t.cached) for t in result.trace)
            rows.append(Row(question_id, attempt, turn_ms, tools))
    return rows


def _median(values: list[int]) -> int | None:
    return round(statistics.median(values)) if values else None


def _stats(stats: CacheStats) -> dict[str, Any]:
    return {"hits": stats.hits, "misses": stats.misses, "hit_rate": round(stats.hit_rate, 3)}


def summarise(rows: list[Row], embed: CacheStats, tool: CacheStats) -> dict[str, Any]:
    """Hit rates and first-vs-repeat medians of `turn_ms` and per-call tool `latency_ms`."""
    out: dict[str, Any] = {"embed": _stats(embed), "tool": _stats(tool)}
    for label, attempt in (("first", 1), ("repeat", 2)):
        picked = [r for r in rows if r.attempt == attempt]
        out[label] = {
            "median_turn_ms": _median([r.turn_ms for r in picked]),
            "median_tool_ms": _median([t.latency_ms for r in picked for t in r.tools]),
        }
    return out


def _tools_cell(row: Row) -> str:
    if not row.tools:
        return "–"
    return ", ".join(f"{t.name} {t.latency_ms} ms {'hit' if t.cached else 'miss'}" for t in row.tools)


def _ms(value: int | None) -> str:
    return "n/a" if value is None else f"{value} ms"


def render_table(rows: list[Row], summary: dict[str, Any]) -> str:
    """Markdown ready to paste into `docs/caching.md`."""
    lines = [
        "| Question | Ask | turn_ms | Tool calls |",
        "|---|---|---|---|",
        *(
            f"| {r.question_id} | {'1st' if r.attempt == 1 else '2nd'} | {r.turn_ms} | {_tools_cell(r)} |"
            for r in rows
        ),
        "",
        "| | Median turn | Median tool call |",
        "|---|---|---|",
        *(
            f"| {label} | {_ms(summary[key]['median_turn_ms'])} | {_ms(summary[key]['median_tool_ms'])} |"
            for label, key in (("First ask", "first"), ("Repeat", "repeat"))
        ),
        "",
        "| Cache | Hits | Misses | Hit rate |",
        "|---|---|---|---|",
        *(
            f"| {name} | {s['hits']} | {s['misses']} | {s['hit_rate']:.1%} |"
            for name, s in (("Embedding", summary["embed"]), ("Tool result", summary["tool"]))
        ),
    ]
    return "\n".join(lines)


async def _measure(pace_s: float) -> tuple[list[Row], CacheStats, CacheStats]:
    settings = load_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set — the cache measurement calls Groq live")
    embed_stats, tool_stats = CacheStats(), CacheStats()
    retriever = build_retriever(
        settings,
        embed_cache=MemoryCache(max_entries=DEFAULT_CACHE_EMBED_MAX, name="embed"),
        stats=embed_stats,
    )
    tools = cached_tools(
        await load_mcp_tools(settings),
        MemoryCache(max_entries=DEFAULT_CACHE_TOOL_MAX, name="tool"),
        tool_stats,
        ttl_s=DEFAULT_CACHE_TOOL_TTL_S,
    )
    client = get_client(settings)
    classify = build_classifier(settings)

    async def ask(message: str) -> ChatResult:
        return await respond(
            message, [], client=client, retriever=retriever, tools=tools, classify=classify, store=None
        )

    return await run_sequence(ask, pace_s=pace_s), embed_stats, tool_stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live cache measurement: repeated questions, cold vs warm.")
    parser.add_argument("--pace", type=float, default=PACE_S, help="seconds between turns (Groq TPM limit)")
    parser.add_argument("--json", type=Path, metavar="PATH", help="also write the raw rows and summary here")
    args = parser.parse_args(argv)

    try:
        rows, embed_stats, tool_stats = asyncio.run(_measure(args.pace))
    except Exception as exc:  # noqa: BLE001 - this boundary converts any setup/run failure to exit 2
        return _fail(f"could not run cache measurement: {exc}", False)

    summary = summarise(rows, embed_stats, tool_stats)
    print(render_table(rows, summary))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rows": [asdict(r) for r in rows], "summary": summary}
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nraw rows: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
