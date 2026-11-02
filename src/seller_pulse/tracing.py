"""Langfuse tracing: one trace per turn, off unless configured, never fatal.

The only module that imports ``langfuse`` (lazily, so the offline test and eval paths never
pay for it). When tracing is off or Langfuse misbehaves, callers get ``NO_TRACE`` and carry on.
"""

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any

from seller_pulse.config import Settings

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

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception:
            logger.warning("tracing: flush failed", exc_info=True)


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
