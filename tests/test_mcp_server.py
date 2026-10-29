import json
from dataclasses import replace
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from seller_pulse.config import Settings
from seller_pulse.mcp_server import build_server
from seller_pulse.tools import INVENTORY_DESCRIPTION, SALES_DESCRIPTION

SETTINGS = Settings(
    llm_provider="groq",
    groq_api_key=None,
    groq_model="test-model",
    server_port=7860,
    chroma_path=Path("unused"),
    seller_id="SELLER-001",
)


async def _call(name, args, settings=SETTINGS):
    async with create_connected_server_and_client_session(build_server(settings)) as session:
        result = await session.call_tool(name, args)
    # Envelope errors are normal results, never MCP errors.
    assert result.isError is False
    return result.structuredContent or json.loads(result.content[0].text)


async def _tools():
    async with create_connected_server_and_client_session(build_server(SETTINGS)) as session:
        return (await session.list_tools()).tools


async def test_tool_names():
    assert [t.name for t in await _tools()] == ["get_sales_analytics", "check_inventory_status", "find_listing", "list_low_stock", "get_top_products", "get_stock_velocity", "get_review_summary"]


@pytest.mark.parametrize("name, args", [("get_sales_analytics", ["period", "sku"]), ("check_inventory_status", ["sku"])])
async def test_schema_hides_seller_id(name, args):
    tool = {t.name: t for t in await _tools()}[name]
    assert list(tool.inputSchema["properties"]) == args
    assert all(tool.inputSchema["properties"][a]["description"] for a in args)
    assert "seller_id" not in json.dumps(tool.inputSchema)


async def test_descriptions_match_in_process_tools():
    tools = {t.name: t for t in await _tools()}
    assert tools["get_sales_analytics"].description == SALES_DESCRIPTION
    assert tools["check_inventory_status"].description == INVENTORY_DESCRIPTION


async def test_sales_tool():
    result = await _call("get_sales_analytics", {"period": "last_week"})
    assert result["ok"] is True
    assert result["data"]["units_sold"] == 904


async def test_inventory_unknown_sku():
    result = await _call("check_inventory_status", {"sku": "SKU-9999"})
    assert result["error"]["code"] == "UNKNOWN_SKU"


async def test_seller_id_is_bound_from_settings():
    other = replace(SETTINGS, seller_id="SELLER-999")
    assert (await _call("check_inventory_status", {"sku": "SKU-1001"}, other))["error"]["code"] == "UNKNOWN_SKU"
    assert (await _call("get_sales_analytics", {"period": "last_week"}, other))["error"]["code"] == "NO_DATA_FOR_PERIOD"
