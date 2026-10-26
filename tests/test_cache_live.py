import asyncio

from seller_pulse.agent import ToolCallRecord
from seller_pulse.cache import CacheStats
from seller_pulse.chat import ChatResult
from seller_pulse.evals.cache_live import SEQUENCE, Row, ToolTiming, render_table, run_sequence, summarise


def _result(*calls: tuple[str, int, bool]) -> ChatResult:
    return ChatResult(
        text="ok",
        trace=[ToolCallRecord(name=n, args={}, result={"ok": True}, cached=c, latency_ms=ms) for n, ms, c in calls],
    )


def test_each_question_is_asked_twice_back_to_back_with_empty_history():
    asked = []

    async def ask(message):
        asked.append(message)
        return _result()

    rows = asyncio.run(run_sequence(ask))
    assert [(r.question_id, r.attempt) for r in rows] == [
        (qid, attempt) for qid, _ in SEQUENCE for attempt in (1, 2)
    ]
    assert asked == [m for _, m in SEQUENCE for _ in (1, 2)]


def test_run_sequence_records_tool_timings():
    async def ask(message):
        return _result(("get_sales_analytics", 900, False))

    [row, *_] = asyncio.run(run_sequence(ask, SEQUENCE[:1]))
    assert row.tools == (ToolTiming("get_sales_analytics", 900, False),)


def _rows():
    return [
        Row("A", 1, 4000, (ToolTiming("t", 1000, False),)),
        Row("A", 2, 3000, (ToolTiming("t", 2, True),)),
        Row("B", 1, 5000, (ToolTiming("t", 800, False),)),
        Row("B", 2, 3500, (ToolTiming("t", 4, True),)),
        Row("P", 1, 2000, ()),
        Row("P", 2, 1800, ()),
    ]


def test_summarise_medians_first_vs_repeat_and_hit_rates():
    summary = summarise(_rows(), CacheStats(hits=5, misses=3), CacheStats(hits=2, misses=2))
    assert summary["first"] == {"median_turn_ms": 4000, "median_tool_ms": 900}
    assert summary["repeat"] == {"median_turn_ms": 3000, "median_tool_ms": 3}
    assert summary["embed"] == {"hits": 5, "misses": 3, "hit_rate": 0.625}
    assert summary["tool"]["hit_rate"] == 0.5


def test_summarise_with_no_tool_calls_has_no_tool_median():
    summary = summarise([Row("P", 1, 100, ()), Row("P", 2, 90, ())], CacheStats(), CacheStats())
    assert summary["first"]["median_tool_ms"] is None
    assert summary["tool"]["hit_rate"] == 0.0


def test_render_table_shows_rows_medians_and_hit_rates():
    table = render_table(_rows(), summarise(_rows(), CacheStats(hits=5, misses=3), CacheStats(hits=2, misses=2)))
    assert "| A | 1st | 4000 | t 1000 ms miss |" in table
    assert "| A | 2nd | 3000 | t 2 ms hit |" in table
    assert "| P | 1st | 2000 | – |" in table
    assert "| Repeat | 3000 ms | 3 ms |" in table
    assert "| Embedding | 5 | 3 | 62.5% |" in table
    assert "| Tool result | 2 | 2 | 50.0% |" in table
