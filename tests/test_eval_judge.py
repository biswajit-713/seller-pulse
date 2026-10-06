from seller_pulse.agent import ToolCallRecord
from seller_pulse.evals.judge import Attempt, DimensionVerdict, Rubric, SuspectVerdict, Verdict, judge

PASS = DimensionVerdict(result="pass", reasons=["ok"], missed=[])
CANNED = Verdict(
    suspects=[SuspectVerdict(value="9.6%", classification="derived", basis="(1000-904)/1000 from trace")],
    accuracy=PASS,
    grounded=PASS,
    behavior=PASS,
)

RUBRIC = Rubric(
    query="How did last week go?",
    query_context=None,
    expected_behavior="States which window it used.",
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
        RUBRIC.expected_behavior,
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
    for dim in (verdict.accuracy, verdict.grounded, verdict.behavior):
        assert dim.result == "fail"
        assert dim.reasons == ["judge error: RuntimeError: rate limited"]


async def test_unparseable_output_becomes_failing_verdict():
    verdict = await judge(FakeJudgeModel(None), RUBRIC, ATTEMPT)
    assert verdict.judge_error
    assert verdict.grounded.result == "fail"
