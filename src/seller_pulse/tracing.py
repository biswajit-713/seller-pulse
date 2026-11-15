"""Langfuse tracing: one trace per turn, off unless configured, never fatal.

The only module that imports ``langfuse`` (lazily, so the offline test and eval paths never
pay for it). When tracing is off or Langfuse misbehaves, callers get ``NO_TRACE`` and carry on.
"""

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from seller_pulse.config import Settings

if TYPE_CHECKING:
    from seller_pulse.agent import ToolCallRecord
    from seller_pulse.guardrails import GuardrailReport
    from seller_pulse.input_rails import RailVerdict
    from seller_pulse.rag.retrieval import RetrievalResult
    from seller_pulse.router import RouteDecision

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnTrace:
    """Handle for one turn's trace. ``trace_id``/``handler`` are None when not tracing."""

    trace_id: str | None = None
    handler: Any = None  # langfuse.langchain.CallbackHandler: pass in LangChain ``callbacks``


NO_TRACE = TurnTrace()


class Tracing:
    def __init__(self, client: Any = None):
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def turn(
        self, name: str = "turn", session_id: str | None = None, **attrs: Any
    ) -> Iterator[TurnTrace]:
        """Open a trace; LangChain calls made with ``.handler`` nest under it.
        ``session_id`` groups the traces of one chat session in Langfuse."""
        if self._client is None:
            yield NO_TRACE
            return
        scope = ExitStack()
        try:
            from langfuse import propagate_attributes
            from langfuse.langchain import CallbackHandler

            trace_id = self._client.create_trace_id()
            scope.enter_context(
                self._client.start_as_current_observation(
                    name=name, as_type="span", trace_context={"trace_id": trace_id}, **attrs
                )
            )
            if session_id:
                scope.enter_context(propagate_attributes(session_id=session_id))
            trace = TurnTrace(trace_id, CallbackHandler())
        except Exception:
            logger.warning("tracing: could not start trace", exc_info=True)
            _close(scope, None, None, None)
            yield NO_TRACE
            return
        try:
            yield trace
        except BaseException as exc:
            _close(scope, type(exc), exc, exc.__traceback__)
            raise
        else:
            _close(scope, None, None, None)

    def record_turn(
        self,
        trace: TurnTrace,
        *,
        decision: "RouteDecision",
        retrieved: "RetrievalResult",
        embed_cache: tuple[int, int] | None,
        tool_calls: "list[ToolCallRecord]",
        report: "GuardrailReport",
        turn_ms: int,
    ) -> None:
        """Write the turn's events as child spans of the open turn trace, plus the numeric
        scores the dashboard aggregates. Call inside ``turn()``. Spans are written after the fact,
        so their own duration is ~0; the real timings are in metadata (``latency_ms``)."""
        client = self._client
        if client is None or trace.trace_id is None:
            return
        try:
            failures = 0
            _span(
                client, "route", "span", None,
                routes=sorted(r.value for r in decision.routes),
                fallback=decision.fallback, latency_ms=decision.latency_ms,
            )
            hits = (*retrieved.reviews, *retrieved.policy)
            embed = {} if embed_cache is None else {"embed_cache_hits": embed_cache[0], "embed_cache_misses": embed_cache[1]}
            _span(
                client, "retrieval", "retriever", None,
                mode=retrieved.mode.value, count=len(hits), stats=retrieved.stats is not None,
                hits=[{"id": h.id, "distance": h.distance} for h in hits], **embed,
            )
            for record in tool_calls:
                ok = bool(record.result.get("ok"))
                code = (record.result.get("error") or {}).get("code")
                failures += not ok
                _span(
                    client, record.name, "tool", None if ok else f"tool failed: {code}",
                    input=record.args, ok=ok, error_code=code, cached=record.cached,
                    latency_ms=record.latency_ms,
                )
            _span(
                client, "guardrail", "guardrail", None,
                triggered=report.triggered, unverified_figures=report.unverified_figures,
                ungrounded_ids=report.ungrounded_ids, draft_pending=report.draft_pending,
                publish_claim=report.publish_claim, policy_refusal=report.policy_refusal,
                policy_clauses=report.policy_clauses,
            )
            client.update_current_span(metadata={"turn_ms": turn_ms})
            for name, value in (
                ("tool_failures", failures),
                ("tool_calls", len(tool_calls)),
                ("guardrail_triggered", int(report.triggered)),
            ):
                client.create_score(
                    name=name, value=float(value), trace_id=trace.trace_id, data_type="NUMERIC"
                )
        except Exception:
            logger.warning("tracing: could not record turn events", exc_info=True)

    def record_input_rail(self, trace: TurnTrace, rail: "RailVerdict") -> None:
        """The input rail's span and an `input_rail_blocked` score. Call inside ``turn()``."""
        client = self._client
        if client is None or trace.trace_id is None:
            return
        try:
            _span(client, "input_rail", "guardrail", None, blocked=rail.blocked, check_failed=rail.error, latency_ms=rail.latency_ms, reason=rail.reason)
            client.create_score(
                name="input_rail_blocked", value=float(rail.blocked), trace_id=trace.trace_id, data_type="NUMERIC"
            )
        except Exception:
            logger.warning("tracing: could not record input rail", exc_info=True)

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception:
            logger.warning("tracing: flush failed", exc_info=True)


def _span(
    client: Any, name: str, as_type: str, error: str | None, input: Any = None, **metadata: Any
) -> None:
    """One finished child span of the current observation; ERROR level when ``error`` is set."""
    client.start_observation(
        name=name, as_type=as_type, input=input, metadata=metadata,
        level="ERROR" if error else None, status_message=error,
    ).end()


def _close(scope: Any, *exc_info: Any) -> None:
    try:
        scope.__exit__(*exc_info)
    except Exception:
        logger.warning("tracing: could not close trace", exc_info=True)


def build_tracing(settings: Settings) -> Tracing:
    logger.info("tracing=%s", "on" if settings.tracing_active else "off")
    if not settings.tracing_active:
        return Tracing()
    try:
        from langfuse import Langfuse

        return Tracing(
            Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        )
    except Exception:
        logger.warning("tracing: client setup failed, tracing off", exc_info=True)
        return Tracing()
