"""Load the sales and inventory tools from the MCP server (`mcp_server.py`) over stdio.

The app consumes its own tools the way it would any third-party MCP server; tests and the agent
eval keep the in-process `tools.build_tools` (no subprocess, comparable baselines).

Per-call spawn: no persistent session is held, so every tool call starts a fresh server
subprocess (`langchain-mcp-adapters`' default). The tools carry only connection config, with no
event-loop affinity — they can be loaded under `asyncio.run` at startup and called from Gradio's
loop. A persistent session is the follow-up if the per-call latency hurts.

Adapter tools return content blocks, not the envelope dict the agent loop, the tool-call log and
the eval checks expect, so each is wrapped to parse its one JSON text block back into the
envelope. A server-side exception (MCP `isError`) makes the adapter raise, which `run_agent`
already turns into a `TOOL_EXCEPTION` envelope.
"""

import json
import logging
import sys

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from seller_pulse.config import Settings

logger = logging.getLogger(__name__)

SERVER_NAME = "seller-pulse"
EXPECTED_TOOLS = frozenset({"get_sales_analytics", "check_inventory_status", "find_listing"})


def server_connection(settings: Settings) -> dict:
    """stdio connection to `mcp_server`, in this interpreter's venv, for the configured seller."""
    # mcp merges `env` onto its safe default environment, so only the tenant is passed.
    return {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "seller_pulse.mcp_server"],
        "env": {"SELLER_ID": settings.seller_id},
    }


def _envelope(content: object) -> dict:
    if isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text":
        result = json.loads(content[0]["text"])
        if isinstance(result, dict):
            return result
    raise ValueError(f"MCP tool returned no JSON envelope: {content!r}")


def _envelope_tool(tool: BaseTool) -> BaseTool:
    """`tool` with its content blocks parsed back into the envelope dict."""

    async def call(**kwargs) -> dict:
        return _envelope(await tool.ainvoke(kwargs))

    return StructuredTool.from_function(
        coroutine=call, name=tool.name, description=tool.description, args_schema=tool.args_schema
    )


async def load_mcp_tools(settings: Settings) -> list[BaseTool]:
    """Both tools over MCP. Raises if the server can't be spawned or lists the wrong tools."""
    client = MultiServerMCPClient({SERVER_NAME: server_connection(settings)})
    tools = await client.get_tools()
    names = sorted(t.name for t in tools)
    # A hard startup error beats an agent missing a tool it is prompted to use.
    if set(names) != EXPECTED_TOOLS:
        raise RuntimeError(f"MCP server listed {names}, expected {sorted(EXPECTED_TOOLS)}")
    logger.info("mcp server spawned, tools=%s", names)
    return [_envelope_tool(t) for t in tools]
