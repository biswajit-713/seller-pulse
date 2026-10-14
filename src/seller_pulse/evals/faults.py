"""Fault injection for the agent eval (ev-07): make one named tool fail for one case.

A case's `fault` swaps that tool for a stand-in with the same name, description and args
schema whose result is the error envelope (`docs/tools.md` §2) — an `ok: false` result, not an
exception, so the agent sees exactly what a real failing tool would hand it. Production code is
untouched: only the tool list the runner passes to `respond` changes.

`args` scopes the fault to matching calls (same matching as a `tool_called` check); a call that
doesn't match goes to the real tool. SQ-37 needs this: `today` times out, but the fallback call
for the last day with data must still return real figures, or there is nothing honest to fall
back on. Without `args`, every call to the tool fails (SQ-24).
"""

from dataclasses import dataclass, field

from langchain_core.tools import BaseTool, StructuredTool

FAULT_MESSAGES = {
    "TIMEOUT": "{tool} timed out before returning a result. No data was retrieved.",
}
FAULT_CODES = frozenset(FAULT_MESSAGES)


@dataclass(frozen=True)
class Fault:
    tool: str
    code: str  # one of FAULT_CODES
    args: dict[str, list] = field(default_factory=dict)  # arg → accepted values; empty = every call

    def matches(self, call_args: dict) -> bool:
        return all(_norm(call_args.get(arg)) in {_norm(v) for v in values} for arg, values in self.args.items())

    def envelope(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": FAULT_MESSAGES[self.code].format(tool=self.tool)}}


def _norm(value: object) -> str:
    return str(value).strip().lower()


def parse_fault(raw: object) -> Fault:
    """`{"tool": ..., "code": ..., "args"?: {arg: value | [values]}}` → `Fault`; `ValueError` if malformed."""
    if not isinstance(raw, dict) or set(raw) - {"tool", "code", "args"}:
        raise ValueError(f"fault needs tool, code and optional args: {raw!r}")
    tool, code, args = raw.get("tool"), raw.get("code"), raw.get("args", {})
    if not isinstance(tool, str) or not tool:
        raise ValueError(f"fault tool must be a tool name: {raw!r}")
    if code not in FAULT_CODES:
        raise ValueError(f"fault code {code!r} not one of {sorted(FAULT_CODES)}")
    if not isinstance(args, dict):
        raise ValueError(f"fault args must be an object: {raw!r}")
    return Fault(tool=tool, code=code, args={k: v if isinstance(v, list) else [v] for k, v in args.items()})


def inject_fault(tools: list[BaseTool], fault: Fault) -> list[BaseTool]:
    """`tools` with `fault.tool` replaced by its failing stand-in. Unknown tool → `ValueError`."""
    if fault.tool not in {t.name for t in tools}:
        raise ValueError(f"fault tool {fault.tool!r} not in the pipeline's tools")
    return [_faulty(t, fault) if t.name == fault.tool else t for t in tools]


def _faulty(real: BaseTool, fault: Fault) -> BaseTool:
    async def call(**kwargs) -> dict:
        if fault.matches(kwargs):
            return fault.envelope()
        return await real.ainvoke(kwargs)

    return StructuredTool.from_function(
        coroutine=call, name=real.name, description=real.description, args_schema=real.args_schema
    )
