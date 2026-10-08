import asyncio
import typing

import langchain_groq
import pytest

from seller_pulse.config import DEFAULT_ROUTER_MODEL, load_settings
from seller_pulse.evals.route_cases import load_route_cases
from seller_pulse.llm import get_router_client
from seller_pulse.router import (
    ALL_ROUTES,
    CLASSIFIER_PROMPT,
    FEW_SHOT,
    HISTORY_CHARS,
    Route,
    RouteSchema,
    build_messages,
    classify_query,
)


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


async def test_duplicate_labels_collapse():
    decision = await classify_query(FakeRouterModel({"routes": ["data", "data"]}), "Sales?", [])
    assert decision.routes == {Route.DATA}


@pytest.mark.parametrize(
    "model",
    [
        FakeRouterModel(error=RuntimeError("groq down")),
        FakeRouterModel({"routes": ["sales"]}),  # unknown label
        FakeRouterModel({"routes": ["memory"]}),  # deferred route: not in the schema
        FakeRouterModel("not a schema"),  # parser handed back something else
    ],
    ids=["exception", "unknown-label", "deferred-label", "unparseable"],
)
async def test_failures_fall_back_to_all_routes(model):
    decision = await classify_query(model, "How did last week go?", [])
    assert decision.routes == ALL_ROUTES
    assert decision.fallback is True


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
    assert 6 <= len(FEW_SHOT) <= 8
    for case_id, message, routes in FEW_SHOT:
        assert message == gold[case_id].message, case_id
        assert frozenset(routes) == gold[case_id].routes, case_id
        assert not gold[case_id].deferred, case_id


def test_router_model_defaults(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.delenv("ROUTER_MODEL", raising=False)
    assert load_settings().router_model == DEFAULT_ROUTER_MODEL


def test_router_model_honours_env(monkeypatch):
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("ROUTER_MODEL", "some/router")
    assert load_settings().router_model == "some/router"


class FakeChatGroq:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_router_client_is_deterministic_and_low_effort(monkeypatch):
    monkeypatch.setattr(langchain_groq, "ChatGroq", FakeChatGroq)
    monkeypatch.setenv("SELLER_ID", "SELLER-001")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("ROUTER_MODEL", raising=False)
    client = get_router_client(load_settings())
    assert client.chat_model.kwargs == {
        "model": DEFAULT_ROUTER_MODEL, "api_key": "k", "temperature": 0, "reasoning_effort": "low",
    }
    assert get_router_client(load_settings(), model="other").chat_model.kwargs["model"] == "other"
