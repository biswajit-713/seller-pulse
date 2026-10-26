import json
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools as adapter_load_tools
from mcp.shared.memory import create_connected_server_and_client_session

from seller_pulse.config import Settings
from seller_pulse.mcp_server import build_server
from seller_pulse.mcp_tools import _envelope_tool, load_mcp_tools
from seller_pulse.tools import INVENTORY_DESCRIPTION

SETTINGS = Settings(
    llm_provider="groq",
    groq_api_key=None,
    groq_model="test-model",
    server_port=7860,
    chroma_path=Path("unused"),
    seller_id="SELLER-001",
)


async def _call_in_memory(name, args):
    async with create_connected_server_and_client_session(build_server(SETTINGS)) as session:
        tools = {t.name: _envelope_tool(t) for t in await adapter_load_tools(session)}
        return tools, await tools[name].ainvoke(args)


async def test_sales_result_is_the_envelope_dict():
    _, result = await _call_in_memory("get_sales_analytics", {"period": "last_week"})
    assert result["ok"] is True
    assert result["data"]["units_sold"] == 904


async def test_envelope_error_is_a_result_not_an_exception():
    _, result = await _call_in_memory("check_inventory_status", {"sku": "SKU-9999"})
    assert result["error"]["code"] == "UNKNOWN_SKU"


async def test_wrapper_keeps_name_description_and_schema():
    tools, _ = await _call_in_memory("check_inventory_status", {"sku": "SKU-1001"})
    tool = tools["check_inventory_status"]
    assert tool.description == INVENTORY_DESCRIPTION
    params = convert_to_openai_tool(tool)["function"]["parameters"]  # what bind_tools sends
    assert list(params["properties"]) == ["sku"]
    assert params["properties"]["sku"]["description"]
    assert "seller_id" not in json.dumps(params)


async def test_non_json_content_raises():
    async def text(sku: str) -> str:
        return "not json"

    fake = StructuredTool.from_function(coroutine=text, name="check_inventory_status", description="d")
    with pytest.raises(ValueError):
        await _envelope_tool(fake).ainvoke({"sku": "SKU-1001"})


async def test_wrong_tool_set_fails_loudly(monkeypatch):
    async def one_tool(self):
        return [StructuredTool.from_function(func=lambda sku: {}, name="check_inventory_status", description="d")]

    monkeypatch.setattr(MultiServerMCPClient, "get_tools", one_tool)
    with pytest.raises(RuntimeError, match="expected"):
        await load_mcp_tools(SETTINGS)


async def test_stdio_spawn_end_to_end():
    """The real subprocess: proves the interpreter, module path and SELLER_ID wiring."""
    tools = {t.name: t for t in await load_mcp_tools(SETTINGS)}
    assert set(tools) == {"get_sales_analytics", "check_inventory_status", "find_listing", "list_low_stock"}
    result = await tools["check_inventory_status"].ainvoke({"sku": "SKU-1001"})
    assert result["data"]["stock_qty"] == 6
