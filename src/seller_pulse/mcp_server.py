"""MCP server exposing the sales and inventory tools over stdio.

Run: `uv run python -m seller_pulse.mcp_server` (needs `SELLER_ID`).

Wrappers only, over the same domain functions as `tools.py`, with the same names and the same
description strings (imported, not retyped) — the two transports must not drift.

`seller_id` is closed over from `Settings`, never a tool argument, for the same reason as in
`tools.py` (see `docs/tools.md` §1).

Envelope errors (`ok: false`, e.g. `UNKNOWN_SKU`) are returned as normal results, not MCP
`isError`: a bad period or unknown SKU is a valid answer, and a tool-failure-rate metric must
not count it. FastMCP sets `isError` only when a tool raises — that's reserved for real faults.

stdio transport: stdout carries the protocol, so nothing here may print to it.
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from seller_pulse.config import Settings, load_settings
from seller_pulse.inventory import check_inventory_status
from seller_pulse.sales import get_sales_analytics
from seller_pulse.tools import (
    INVENTORY_DESCRIPTION,
    PERIOD_DESCRIPTION,
    SALES_DESCRIPTION,
    SKU_DESCRIPTION,
)


def build_server(settings: Settings) -> FastMCP:
    """MCP server with both tools, seller_id closed over from settings."""
    seller_id = settings.seller_id
    server = FastMCP("seller-pulse")

    @server.tool(name="get_sales_analytics", description=SALES_DESCRIPTION)
    def sales(period: Annotated[str, Field(description=PERIOD_DESCRIPTION)]) -> dict:
        return get_sales_analytics(seller_id, period)

    @server.tool(name="check_inventory_status", description=INVENTORY_DESCRIPTION)
    def inventory(sku: Annotated[str, Field(description=SKU_DESCRIPTION)]) -> dict:
        return check_inventory_status(seller_id, sku)

    return server


if __name__ == "__main__":
    build_server(load_settings()).run()  # stdio
