"""LangChain tool wrappers over the sales and inventory domain functions and the preference
store.

Wrappers only — no logic. w2-10 wraps the same domain functions for MCP; logic here would make
the two transports drift.

`seller_id` is closed over from `Settings`, never an LLM-visible argument: if the model could
pass it, a prompt injection could ask for another tenant's data (see `docs/tools.md` §1).
Tool descriptions say what each tool is for and what data it returns — that's for tool
selection. Argument formats (period grammar, SKU form) sit on the argument's own schema
description.
How to act on a result (error codes, no-data-is-not-zero) lives in the system prompt (w2-08),
not here. Keep them in sync with `docs/tools.md`. Exception: the memory tools carry their own
when-to-save and confirm-back instructions, since no prompt module exists for them (w2-13b).
"""

from typing import Annotated

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field

from seller_pulse.config import Settings
from seller_pulse.inventory import check_inventory_status, find_listing, list_low_stock
from seller_pulse.memory import PreferenceKey, PreferenceStore
from seller_pulse.sales import MAX_TOP_PRODUCTS, PERIOD_GRAMMAR, get_sales_analytics, get_top_products

SALES_DESCRIPTION = (
    "Revenue (USD), units sold and order lines for one inclusive date window, plus the "
    "previous window of the same length for a trend, and how many days in each window have "
    "data. Covers the whole store, or one SKU when a SKU is given. Use this for any sales "
    "figure — never estimate."
)

TOP_PRODUCTS_DESCRIPTION = (
    "The seller's best sellers (units sold, revenue in USD) for one inclusive date window, "
    "ranked by revenue or units, per product (SKU, title) or per category. Use this for any "
    "best-seller, top-product, top-category or ranking question — never call "
    "get_sales_analytics SKU by SKU."
)

METRIC_DESCRIPTION = "What to rank by: 'revenue' (default) or 'units'."

LIMIT_DESCRIPTION = f"How many products or categories to return, 1 to {MAX_TOP_PRODUCTS}. Default 5."

GROUP_BY_DESCRIPTION = (
    "'sku' (default) ranks individual products; 'category' sums listings per category — use it "
    "for category questions, with a limit big enough to list every category."
)

PERIOD_DESCRIPTION = f"One of: {PERIOD_GRAMMAR}. Weeks run Mon–Sun."

INVENTORY_DESCRIPTION = (
    "Current stock quantity, listing status, title and price for one SKU. "
    "Use this for any stock figure — never estimate."
)

SKU_DESCRIPTION = "The SKU code, in the form SKU-1234."

SALES_SKU_DESCRIPTION = (
    "Optional SKU code, in the form SKU-1234, to report that one listing's sales instead of "
    "the whole store's. Omit for store-wide figures."
)

FIND_LISTING_DESCRIPTION = (
    "Find the seller's listing SKUs from a product name, as the seller wrote it (case, spacing and "
    "small typos are fine). Use this first whenever the seller names a product instead of giving "
    "a SKU."
)

LISTING_NAME_DESCRIPTION = "The product name or a distinctive part of it, e.g. 'Boho Wall Hanging'."

LOW_STOCK_DESCRIPTION = (
    "Every listing in the seller's catalog at or below a stock level, lowest first, with SKU, "
    "title, current quantity and status. Use this for any question about which products are low "
    "or out of stock — never check SKUs one by one."
)

THRESHOLD_DESCRIPTION = "Units at or below which a listing counts as low, a whole number, 0 or more."

SAVE_PREFERENCE_DESCRIPTION = (
    "Remember one of the seller's lasting preferences across sessions, replacing any earlier "
    "value. Call only when the seller states or changes a preference — never for a question "
    "that merely applies one. Afterwards, confirm back exactly what was saved, including any "
    "threshold you chose for them, and if previous_value is set, say what it changed from."
)

PREFERENCE_KEY_DESCRIPTION = (
    "notification_cadence: when to alert and on what, as one line keeping both "
    "(e.g. 'every Friday: best-sellers at or below the restock threshold'); "
    "reply_tone: how buyer replies should sound; "
    "restock_threshold: stock level at or below which a SKU counts as low."
)

PREFERENCE_VALUE_DESCRIPTION = (
    "The preference in the seller's own terms. For restock_threshold, a whole number of units."
)

LIST_PREFERENCES_DESCRIPTION = (
    "Every preference the seller has saved (notification cadence, reply tone, restock "
    "threshold), with when each was last updated."
)


def build_tools(settings: Settings) -> list[BaseTool]:
    """In-process tools, seller_id closed over from settings."""
    seller_id = settings.seller_id

    def sales(
        period: Annotated[str, Field(description=PERIOD_DESCRIPTION)],
        sku: Annotated[str | None, Field(description=SALES_SKU_DESCRIPTION)] = None,
    ) -> dict:
        return get_sales_analytics(seller_id, period, sku)

    def inventory(sku: Annotated[str, Field(description=SKU_DESCRIPTION)]) -> dict:
        return check_inventory_status(seller_id, sku)

    def listing(name: Annotated[str, Field(description=LISTING_NAME_DESCRIPTION)]) -> dict:
        return find_listing(seller_id, name)

    def low_stock(threshold: Annotated[int, Field(description=THRESHOLD_DESCRIPTION)]) -> dict:
        return list_low_stock(seller_id, threshold)

    def top_products(
        period: Annotated[str, Field(description=PERIOD_DESCRIPTION)],
        metric: Annotated[str, Field(description=METRIC_DESCRIPTION)] = "revenue",
        limit: Annotated[int, Field(description=LIMIT_DESCRIPTION)] = 5,
        group_by: Annotated[str, Field(description=GROUP_BY_DESCRIPTION)] = "sku",
    ) -> dict:
        return get_top_products(seller_id, period, metric, limit, group_by)

    return [
        StructuredTool.from_function(
            func=sales, name="get_sales_analytics", description=SALES_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=inventory, name="check_inventory_status", description=INVENTORY_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=listing, name="find_listing", description=FIND_LISTING_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=low_stock, name="list_low_stock", description=LOW_STOCK_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=top_products, name="get_top_products", description=TOP_PRODUCTS_DESCRIPTION
        ),
    ]


def build_memory_tools(store: PreferenceStore) -> list[BaseTool]:
    """In-process preference tools over one seller's store (bound to that seller's file).

    Not on the MCP server: they write local per-seller state, and #15 only asks for the two
    analytics tools over MCP.
    """

    def save(
        key: Annotated[PreferenceKey, Field(description=PREFERENCE_KEY_DESCRIPTION)],
        value: Annotated[str, Field(description=PREFERENCE_VALUE_DESCRIPTION)],
    ) -> dict:
        try:
            pref = store.upsert(key, value)
        except ValueError as e:
            return {"ok": False, "error": {"code": "INVALID_PREFERENCE", "message": str(e)}}
        return {
            "ok": True,
            "data": {"key": pref.key, "value": pref.value, "previous_value": pref.previous_value},
        }

    def list_all() -> dict:
        prefs = store.get_all()
        return {
            "ok": True,
            "data": {
                "preferences": {
                    key: {"value": p.value, "updated_at": p.updated_at} for key, p in prefs.items()
                }
            },
        }

    return [
        StructuredTool.from_function(
            func=save, name="save_preference", description=SAVE_PREFERENCE_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=list_all, name="list_preferences", description=LIST_PREFERENCES_DESCRIPTION
        ),
    ]
