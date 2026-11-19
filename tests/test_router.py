import asyncio
import typing
from pathlib import Path

import langchain_groq
import pytest

from seller_pulse.config import Settings, load_settings
from seller_pulse.evals.route_cases import load_route_cases
from seller_pulse.router import (
    ALL_ROUTES,
    CLASSIFIER_PROMPT,
    FEW_SHOT,
    HISTORY_CHARS,
    Route,
    RouteSchema,
    build_classifier,
    build_messages,
    classify_query,
    route_all,
    tools_for,
)
from seller_pulse.tools import build_tools


class FakeRouterModel:
    """Stands in for a chat model's `with_structured_output(...).ainvoke`."""

    def __init__(self, reply=None, error: Exception | None = None, delay_s: float = 0) -> None:
        self.reply, self.error, self.delay_s = reply, error, delay_s
        self.schema = None
        self.kwargs: dict = {}
        self.seen: list = []

    def with_structured_output(self, schema, **kwargs):
        self.schema, self.kwargs = schema, kwargs
        return self

    def with_config(self, **config):
        self.config = config
        return self

    async def ainvoke(self, messages):
        self.seen.append(messages)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error:
            raise self.error
        # Validate like the real parser does, so an unknown label raises here.
        return self.schema.model_validate(self.reply) if isinstance(self.reply, dict) else self.reply


def _human(model: FakeRouterModel) -> str:
    [messages] = model.seen
    return messages[-1].content


async def test_callbacks_attach_to_the_classifier_call():
    model = FakeRouterModel({"routes": ["data"]})
    await classify_query(model, "q", [], callbacks=["handler"])
    assert model.config == {"callbacks": ["handler"]}


async def test_multi_label_answer_is_parsed():
    model = FakeRouterModel({"routes": ["data", "policy"]})
    decision = await classify_query(model, "Any listings still live with no stock?", [])
    assert decision.routes == {Route.DATA, Route.POLICY}
    assert decision.fallback is False
    assert decision.latency_ms >= 0
    assert model.schema is RouteSchema
    assert model.kwargs == {"method": "json_schema", "strict": True}


async def test_empty_list_stays_empty():
    decision = await classify_query(FakeRouterModel({"routes": []}), "What do rivals charge?", [])
    assert decision.routes == frozenset()
    assert decision.fallback is False


async def test_memory_is_a_valid_answer():
    model = FakeRouterModel({"routes": ["memory", "reviews"]})
    decision = await classify_query(model, "Keep my replies short.", [])
    assert decision.routes == {Route.MEMORY, Route.REVIEWS}
    assert decision.fallback is False


async def test_duplicate_labels_collapse():
    decision = await classify_query(FakeRouterModel({"routes": ["data", "data"]}), "Sales?", [])
    assert decision.routes == {Route.DATA}


@pytest.mark.parametrize(
    "model",
    [
        FakeRouterModel(error=RuntimeError("groq down")),
        FakeRouterModel({"routes": ["sales"]}),  # unknown label
        FakeRouterModel("not a schema"),  # parser handed back something else
    ],
    ids=["exception", "unknown-label", "unparseable"],
)
async def test_failures_fall_back_to_all_routes(model):
    decision = await classify_query(model, "How did last week go?", [])
    assert decision.routes == ALL_ROUTES
    assert decision.fallback is True


class FlakyRouterModel(FakeRouterModel):
    """Fails the first `failures` calls, then answers (a provider's transient empty reply)."""

    def __init__(self, reply, failures: int) -> None:
        super().__init__(reply)
        self.failures, self.calls = failures, 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls <= self.failures:
            return "empty"  # not a RouteSchema -> unparseable
        return await super().ainvoke(messages)


async def test_one_transient_failure_is_retried():
    model = FlakyRouterModel({"routes": ["data"]}, failures=1)
    decision = await classify_query(model, "Sales?", [])
    assert decision.fallback is False
    assert decision.routes == frozenset({Route.DATA})
    assert model.calls == 2


async def test_two_failures_still_fall_back_after_one_retry():
    model = FlakyRouterModel({"routes": ["data"]}, failures=2)
    decision = await classify_query(model, "Sales?", [])
    assert decision.fallback is True
    assert model.calls == 2


async def test_timeout_falls_back_to_all_routes():
    model = FakeRouterModel({"routes": ["data"]}, delay_s=1)
    decision = await classify_query(model, "How did last week go?", [], timeout_s=0.01)
    assert decision.routes == ALL_ROUTES
    assert decision.fallback is True
    assert decision.latency_ms < 1000


async def test_history_is_cut_to_last_exchange_and_truncated():
    history = [
        {"role": "user", "content": "OLDEST question"},
        {"role": "assistant", "content": "OLDEST answer"},
        {"role": "user", "content": "How did my sales perform last week?"},
        {"role": "assistant", "content": "Revenue was $4,210. " + "x" * 1000},
    ]
    model = FakeRouterModel({"routes": ["data"]})
    await classify_query(model, "and the week before?", history)
    text = _human(model)
    assert "OLDEST" not in text
    assert "User: How did my sales perform last week?" in text
    assert "Revenue was $4,210." in text
    assert "x" * (HISTORY_CHARS + 1) not in text
    assert text.endswith("Message to route:\nand the week before?")


def test_no_history_sends_only_the_message():
    [system, human] = build_messages("Sales?", [])
    assert system.content == CLASSIFIER_PROMPT
    assert human.content == "Message to route:\nSales?"


def test_schema_labels_match_built_routes():
    [labels] = typing.get_args(RouteSchema.model_fields["routes"].annotation)
    assert set(typing.get_args(labels)) == {r.value for r in ALL_ROUTES}


def test_few_shot_matches_gold_labels():
    gold = {case.id: case for case in load_route_cases()}
    assert 6 <= len(FEW_SHOT) <= 9
    for case_id, message, routes in FEW_SHOT:
        assert message == gold[case_id].message, case_id
        assert frozenset(routes) == gold[case_id].routes, case_id


class FakeChatGroq:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


async def test_route_all_is_every_route_without_fallback():
    decision = await route_all("anything", [])
    assert decision.routes == ALL_ROUTES
    assert decision.fallback is False
    assert decision.latency_ms == 0


def test_build_classifier_off_skips_the_router_model(monkeypatch):
    monkeypatch.setattr(langchain_groq, "ChatGroq", FakeChatGroq)
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("ROUTING", "off")
    assert build_classifier(load_settings()) is route_all


def test_review_summary_bound_on_reviews_route_only():
    tools = build_tools(Settings(
        llm_provider="groq",
        groq_api_key=None,
        groq_model="test-model",
        server_port=7860,
        chroma_path=Path("unused"),
        seller_id="SELLER-001",
    ))
    bound = lambda routes: {t.name for t in tools_for(frozenset(routes), tools)}
    assert "get_review_summary" in bound({Route.REVIEWS})
    assert "get_review_summary" not in bound({Route.DATA, Route.POLICY})
