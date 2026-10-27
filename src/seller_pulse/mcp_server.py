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
from seller_pulse.inventory import check_inventory_status, find_listing, list_low_stock
from seller_pulse.sales import get_sales_analytics
from seller_pulse.tools import (
    FIND_LISTING_DESCRIPTION,
    INVENTORY_DESCRIPTION,
    LISTING_NAME_DESCRIPTION,
    LOW_STOCK_DESCRIPTION,
    PERIOD_DESCRIPTION,
    SALES_DESCRIPTION,
    SALES_SKU_DESCRIPTION,
    SKU_DESCRIPTION,
    THRESHOLD_DESCRIPTION,
)


def build_server(settings: Settings) -> FastMCP:
    """MCP server with the analytics tools, seller_id closed over from settings."""
    seller_id = settings.seller_id
    server = FastMCP("seller-pulse")

    @server.tool(name="get_sales_analytics", description=SALES_DESCRIPTION)
    def sales(
        period: Annotated[str, Field(description=PERIOD_DESCRIPTION)],
        sku: Annotated[str | None, Field(description=SALES_SKU_DESCRIPTION)] = None,
    ) -> dict:
        return get_sales_analytics(seller_id, period, sku)

    @server.tool(name="check_inventory_status", description=INVENTORY_DESCRIPTION)
    def inventory(sku: Annotated[str, Field(description=SKU_DESCRIPTION)]) -> dict:
        return check_inventory_status(seller_id, sku)

    @server.tool(name="find_listing", description=FIND_LISTING_DESCRIPTION)
    def listing(name: Annotated[str, Field(description=LISTING_NAME_DESCRIPTION)]) -> dict:
        return find_listing(seller_id, name)

    @server.tool(name="list_low_stock", description=LOW_STOCK_DESCRIPTION)
    def low_stock(threshold: Annotated[int, Field(description=THRESHOLD_DESCRIPTION)]) -> dict:
        return list_low_stock(seller_id, threshold)

    return server


if __name__ == "__main__":
    build_server(load_settings()).run()  # stdio
