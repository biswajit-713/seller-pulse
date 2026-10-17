"""Render a `ChatResult` as the Markdown shown in the UI's "Agent trace" panel (w2-16).

Tool calls show name, args and outcome only — not the result payload — so the panel stays
readable. Values come from the model and the seller, so they go inside code spans with any
backtick swapped out; that keeps them from being read as Markdown.
"""

import json

from seller_pulse.agent import ToolCallRecord
from seller_pulse.chat import ChatResult

NO_TOOL_CALLS = "_No tool calls_"
NO_PREFERENCES = "_No stored preferences_"


def _code(text: str) -> str:
    return f"`{text.replace('`', "'")}`"


def _tool_line(record: ToolCallRecord) -> str:
    args = json.dumps(record.args, ensure_ascii=False, sort_keys=True)
    if record.result.get("ok"):
        outcome = "✓ ok"
    else:
        code = (record.result.get("error") or {}).get("code") or "UNKNOWN"
        outcome = f"✗ {_code(code)}"
    return f"- {_code(record.name)} {_code(args)} — {outcome}"


def render_trace(result: ChatResult) -> str:
    routes = ", ".join(sorted(r.value for r in result.routes)) or "none"
    if result.route_fallback:
        routes += " (fallback: all routes)"
    tools = [_tool_line(r) for r in result.trace] or [NO_TOOL_CALLS]
    prefs = [
        f"- {_code(p.key)} → {_code(p.value)}" for p in result.preferences
    ] or [NO_PREFERENCES]
    return "\n".join(
        [
            f"**Routes:** {routes}",
            "",
            "**Tool calls**",
            *tools,
            "",
            "**Preferences applied**",
            *prefs,
        ]
    )
