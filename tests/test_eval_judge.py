from seller_pulse.agent import ToolCallRecord
from seller_pulse.evals.judge import Attempt, DimensionVerdict, PointVerdict, Rubric, SuspectVerdict, Verdict, judge

PASS = DimensionVerdict(result="pass", reasons=["ok"], missed=[])
CANNED = Verdict(
    suspects=[SuspectVerdict(value="9.6%", classification="derived", basis="(1000-904)/1000 from trace")],
    points=[PointVerdict(point=1, met=True, evidence="Mon-Sun 2026-09-14..20")],
    accuracy=PASS,
    grounded=PASS,
)

RUBRIC = Rubric(
    query="How did last week go?",
    query_context=None,
    must=("States which window it used.", "Compares against the prior week."),
    expected_answer="904 orders, $41,904.71 revenue.",
    notes="last_7_days figures also accepted",
)
TRACE = [ToolCallRecord(name="get_sales_analytics", args={"period": "last_week"}, result={"ok": True, "data": {"orders": 904}})]
ATTEMPT = Attempt(
    answer="Last week: 904 orders, down 9.6%.",
    trace=TRACE,
    retrieved_context="<retrieved_context>REV-567</retrieved_context>",
    suspects=["9.6%"],
)


class FakeJudgeModel:
    """Stands in for a chat model's `with_structured_output(...).ainvoke`."""

    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply, self.error = reply, error
        self.schema = None
        self.seen: list = []

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, messages):
        self.seen.append(messages)
        if self.error:
            raise self.error
        return self.reply


def _prompt(model: FakeJudgeModel) -> str:
    [messages] = model.seen
    return "\n".join(m.content for m in messages)


async def test_verdict_returned_unchanged():
    model = FakeJudgeModel(CANNED)
    assert await judge(model, RUBRIC, ATTEMPT) == CANNED
    assert model.schema is Verdict


async def test_prompt_carries_every_input():
    model = FakeJudgeModel(CANNED)
    await judge(model, RUBRIC, ATTEMPT)
    prompt = _prompt(model)
    for needle in [
        RUBRIC.query,
        "1. States which window it used.",
        "2. Compares against the prior week.",
        RUBRIC.expected_answer,
        RUBRIC.notes,
        ATTEMPT.retrieved_context,
        ATTEMPT.answer,
        '"name": "get_sales_analytics"',
        '"period": "last_week"',
        '"orders": 904',
        "- 9.6%",
    ]:
        assert needle in prompt


async def test_empty_suspects_said_explicitly():
    model = FakeJudgeModel(CANNED)
    await judge(model, RUBRIC, Attempt(answer="a", trace=[], retrieved_context="", suspects=[]))
    prompt = _prompt(model)
    assert "SUSPECTS" in prompt
    assert "return an empty suspects list" in prompt


async def test_model_error_becomes_failing_verdict():
    verdict = await judge(FakeJudgeModel(error=RuntimeError("rate limited")), RUBRIC, ATTEMPT)
    assert verdict.judge_error
    assert verdict.points == []
    for dim in (verdict.accuracy, verdict.grounded):
        assert dim.result == "fail"
        assert dim.reasons == ["judge error: RuntimeError: rate limited"]


async def test_unparseable_output_becomes_failing_verdict():
    verdict = await judge(FakeJudgeModel(None), RUBRIC, ATTEMPT)
    assert verdict.judge_error
    assert verdict.grounded.result == "fail"


class _FlakyJudge:
    """Fails with a malformed-tool-call error `fails` times, then returns CANNED."""

    def __init__(self, fails: int) -> None:
        self.fails, self.calls = fails, 0

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("400 tool call validation failed: missing 'points'")
        return CANNED


async def test_transient_judge_error_is_retried():
    model = _FlakyJudge(fails=2)
    verdict = await judge(model, RUBRIC, ATTEMPT, retry_delay_s=0)
    assert verdict == CANNED and model.calls == 2 + 1


async def test_persistent_judge_error_still_a_judge_error_after_retries():
    model = _FlakyJudge(fails=99)
    verdict = await judge(model, RUBRIC, ATTEMPT, retry_delay_s=0)
    assert verdict.judge_error and model.calls == 3
