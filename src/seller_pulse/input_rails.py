"""Input rail (w4-09): a NeMo Guardrails `self check input` check on the cleaned user message,
run before the agent. The only module that imports ``nemoguardrails`` (lazily, so the offline
test path and `INPUT_RAILS=off` never pay for it). See `docs/nemo.md` for the spike.

Fails **open**, like the router: any NeMo error, timeout or build failure is a pass. NeMo itself
fails closed on an empty judge answer, so the wrapper cannot rely on its default.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from seller_pulse.config import Settings
from seller_pulse.llm.factory import get_router_client

logger = logging.getLogger(__name__)

NEMO_CONFIG_DIR = Path(__file__).parent / "nemo"
RAIL_TIMEOUT_S = 4.0  # same budget as the router
BLOCKED_REPLY = (
    "I can't help with that request. I can answer questions about your sales, inventory, "
    "reviews and the marketplace seller policy."
)


@dataclass(frozen=True)
class RailVerdict:
    blocked: bool
    latency_ms: int
    error: bool = False  # the check failed and was treated as a pass
    reason: str | None = None  # the judge's one-line reason; logged/traced only, never shown to the user


# `build_input_rail`'s result; a callable so tests can fake it without NeMo or a model.
# Must not raise: the real one fails open itself.
InputRail = Callable[[str], Awaitable[RailVerdict]]


def _reason(completion: str) -> str | None:
    """The text after "Reason:" in the judge's completion, if it gave one."""
    _, sep, reason = completion.partition("Reason:")
    return reason.strip() or None if sep else None


def build_input_rail(settings: Settings) -> InputRail | None:
    """The rail `chat.respond` takes, or None when `Settings.input_rails` is off."""
    if not settings.input_rails:
        return None
    rails = None  # built on first use, once

    async def check(message: str) -> RailVerdict:
        nonlocal rails
        started = time.perf_counter()

        def verdict(blocked: bool, error: bool = False, reason: str | None = None) -> RailVerdict:
            return RailVerdict(blocked, int((time.perf_counter() - started) * 1000), error, reason)

        try:
            from nemoguardrails import LLMRails, RailsConfig
            from nemoguardrails.integrations.langchain.llm_adapter import LangChainLLMAdapter

            if rails is None:
                llm = LangChainLLMAdapter(get_router_client(settings).chat_model)
                rails = LLMRails(RailsConfig.from_path(str(NEMO_CONFIG_DIR)), llm=llm)
            # generate_async rather than check_async: only the former returns the judge's raw
            # completion (llm_calls), which carries the reason.
            response = await asyncio.wait_for(
                rails.generate_async(
                    messages=[{"role": "user", "content": message}],
                    options={"rails": ["input"], "log": {"activated_rails": True, "llm_calls": True}},
                ),
                RAIL_TIMEOUT_S,
            )
        except Exception:
            logger.warning("input rail failed; treating the message as passed", exc_info=True)
            return verdict(False, error=True)
        blocked = any(r.stop for r in response.log.activated_rails)
        completions = [
            c.completion or ""
            for r in response.log.activated_rails
            for a in r.executed_actions
            for c in a.llm_calls or []
        ]
        return verdict(blocked, reason=_reason(completions[-1]) if blocked and completions else None)

    return check
