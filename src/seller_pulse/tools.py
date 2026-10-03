"""LangChain tool wrappers over the sales and inventory domain functions.

Wrappers only — no logic. w2-10 wraps the same domain functions for MCP; logic here would make
the two transports drift.

`seller_id` is closed over from `Settings`, never an LLM-visible argument: if the model could
pass it, a prompt injection could ask for another tenant's data (see `docs/tools.md` §1).
Tool descriptions say what each tool is for and what data it returns — that's for tool
selection. Argument formats (period grammar, SKU form) sit on the argument's own schema
description.
How to act on a result (error codes, no-data-is-not-zero) lives in the system prompt (w2-08),
not here. Keep them in sync with `docs/tools.md`.
"""

from typing import Annotated

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field

from seller_pulse.config import Settings
from seller_pulse.inventory import check_inventory_status
from seller_pulse.sales import PERIOD_GRAMMAR, get_sales_analytics

SALES_DESCRIPTION = (
    "Revenue (USD), units sold and order lines for one inclusive date window, plus the "
    "previous window of the same length for a trend, and how many days in each window have "
    "data. Use this for any sales figure — never estimate."
)

PERIOD_DESCRIPTION = f"One of: {PERIOD_GRAMMAR}. Weeks run Mon–Sun."

INVENTORY_DESCRIPTION = (
    "Current stock quantity, listing status, title and price for one SKU. "
    "Use this for any stock figure — never estimate."
)

SKU_DESCRIPTION = "The SKU code, in the form SKU-1234."


def build_tools(settings: Settings) -> list[BaseTool]:
    """In-process tools, seller_id closed over from settings."""
    seller_id = settings.seller_id

    def sales(period: Annotated[str, Field(description=PERIOD_DESCRIPTION)]) -> dict:
        return get_sales_analytics(seller_id, period)

    def inventory(sku: Annotated[str, Field(description=SKU_DESCRIPTION)]) -> dict:
        return check_inventory_status(seller_id, sku)

    return [
        StructuredTool.from_function(
            func=sales, name="get_sales_analytics", description=SALES_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=inventory, name="check_inventory_status", description=INVENTORY_DESCRIPTION
        ),
    ]
