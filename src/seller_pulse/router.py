"""Prompt routing: which prompt modules (and tools) a turn needs (`plan/rt-00-overview.md`).

Not to be confused with `rag.retrieval.Route` (stats / general), which picks the *retrieval*
shape. That one is renamed when routing is wired into `chat.respond` (rt-06).

`classify_query` (rt-04) is one `with_structured_output` call on a small model. It is
multi-label (an empty set means core prompt only) and fails open: any exception, timeout or
unparseable answer routes to `ALL_ROUTES`, because a missed `policy` is the expensive mistake
and an extra module only costs tokens.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from seller_pulse.llm.base import Message

logger = logging.getLogger(__name__)


class Route(StrEnum):
    DATA = "data"  # sales, inventory, figures, forecasts -> tool rules, tools bound
    REVIEWS = "reviews"  # review search/stats, listings, drafts, rewrites
    POLICY = "policy"  # anything that might touch a marketplace rule -> refusal procedure
    MEMORY = "memory"  # saved preferences -> memory tools (w2-13); gold label only, no module yet


# Routes that are labelled in the gold set but not built yet. Cases carrying one are skipped in
# the classifier eval until the route lands.
DEFERRED_ROUTES = frozenset({Route.MEMORY})

# Every route that is built. The fail-open answer: a classifier error routes here.
ALL_ROUTES = frozenset(Route) - DEFERRED_ROUTES

CLASSIFY_TIMEOUT_S = 4.0
# Strict JSON-schema output (rt-05): both gpt-oss candidates accept it on Groq, and unlike
# function calling the answer is constrained to the schema rather than merely asked for.
STRUCTURED_OUTPUT = {"method": "json_schema", "strict": True}
# Each side of the previous exchange is cut to this many characters: enough to show the topic
# of a follow-up ("and the week before?"), not enough to pay for a long answer twice.
HISTORY_CHARS = 300


class RouteSchema(BaseModel):
    """What the classifier returns. Must list exactly `ALL_ROUTES` (a test pins it)."""

    routes: list[Literal["data", "reviews", "policy"]]


@dataclass(frozen=True)
class RouteDecision:
    routes: frozenset[Route]
    fallback: bool  # True if we failed open
    latency_ms: int


# (route_cases id, message, gold routes). Kept in step with `route_cases.jsonl` by a test.
# SQ-14 and SQ-25 — the policy cases with no policy vocabulary — are deliberately left out so
# the eval still measures them out of sample. rt-05 reports these ids separately.
FEW_SHOT: tuple[tuple[str, str, tuple[Route, ...]], ...] = (
    ("SQ-01", "How did my sales perform last week?", (Route.DATA,)),
    ("SQ-12", "What are buyers complaining about most?", (Route.REVIEWS,)),
    ("SQ-02", "Why is my 'Boho Wall Hanging' listing underperforming?", (Route.DATA, Route.REVIEWS)),
    ("SQ-06", "Can you offer buyers a free gift for leaving a 5-star review?", (Route.POLICY,)),
    (
        "SQ-07",
        "Are any of my listings still taking orders after they ran out of stock?",
        (Route.DATA, Route.POLICY),
    ),
    (
        "SQ-18",
        "The buyer who left me a 1-star about shipping - can I refund their shipping if they "
        "bump it to 4 stars?",
        (Route.POLICY, Route.REVIEWS),
    ),
    ("SQ-20", "List the wool area rug as 'was $149, now $109' - it'll convert better.", (Route.POLICY,)),
    ("SQ-31", "What are other sellers charging for similar items, and can I see their sales?", ()),
)
FEW_SHOT_IDS = frozenset(case_id for case_id, _, _ in FEW_SHOT)


def _render_few_shot() -> str:
    lines = []
    for _, message, routes in FEW_SHOT:
        labels = ", ".join(f'"{r.value}"' for r in routes)
        lines.append(f"Message: {message}\nroutes: [{labels}]")
    return "\n\n".join(lines)


CLASSIFIER_PROMPT = f"""\
You route messages for Seller Pulse, an assistant for a solo marketplace seller. Decide which \
instruction modules the assistant needs to answer the seller's message. Pick every route that \
applies; return an empty list if none does.

Routes:
- data: sales, revenue, orders, inventory and stock levels, best-sellers, forecasts — anything \
answered with figures from the sales or inventory tools.
- reviews: buyer reviews, review statistics and complaints, replies to reviews, and drafting or \
rewriting listing copy.
- policy: anything that might touch a marketplace rule — product claims, pricing and discounts, \
titles, photos, incentives to buyers, refunds tied to reviews, compliance or policy audits.

If the request asks to change a listing, price, title, photo or claim, or offers anything to a \
buyer, include policy. A new claim about a product also needs reviews, to check it against what \
buyers report.

A shop-wide check against marketplace rules (an audit, "is anything at risk") needs all three \
routes: stock and listing status come from the tools, claims are checked against reviews.

There is no orders table: cancellations, returns and delivery problems are known only from \
buyer reviews, so they are reviews, not data.

A previous exchange may be shown. Use it only to understand a short follow-up (e.g. "and the \
week before?" after a sales answer is data); route the new message, not the old one.

Examples:

{_render_few_shot()}
"""


def _truncate(text: str) -> str:
    return text if len(text) <= HISTORY_CHARS else text[:HISTORY_CHARS] + "…"


def build_messages(question: str, history: list[Message]) -> list:
    """The classifier's input: the prompt, then the last exchange (if any) and the message."""
    parts = []
    previous = history[-2:]  # the last user + assistant turn only
    if previous:
        exchange = "\n".join(f"{m['role'].capitalize()}: {_truncate(m['content'])}" for m in previous)
        parts.append(f"Previous exchange:\n{exchange}")
    parts.append(f"Message to route:\n{question}")
    return [SystemMessage(content=CLASSIFIER_PROMPT), HumanMessage(content="\n\n".join(parts))]


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


async def classify_query(
    model: BaseChatModel,
    question: str,
    history: list[Message],
    *,
    timeout_s: float = CLASSIFY_TIMEOUT_S,
) -> RouteDecision:
    """Route one message. Never raises: any failure returns `ALL_ROUTES` with `fallback=True`."""
    start = time.perf_counter()
    try:
        answer = await asyncio.wait_for(
            model.with_structured_output(RouteSchema, **STRUCTURED_OUTPUT).ainvoke(
                build_messages(question, history)
            ),
            timeout=timeout_s,
        )
        if not isinstance(answer, RouteSchema):
            raise TypeError(f"unparseable output: {answer!r}")
    except Exception as exc:  # TimeoutError included
        latency_ms = _elapsed_ms(start)
        logger.warning(
            "router fallback to all routes after %d ms: %s: %s", latency_ms, type(exc).__name__, exc
        )
        return RouteDecision(routes=ALL_ROUTES, fallback=True, latency_ms=latency_ms)
    return RouteDecision(
        routes=frozenset(Route(r) for r in answer.routes), fallback=False, latency_ms=_elapsed_ms(start)
    )
