import json
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from seller_pulse.config import Settings
from seller_pulse.tools import build_tools

SETTINGS = Settings(
    llm_provider="groq",
    groq_api_key=None,
    groq_model="test-model",
    server_port=7860,
    chroma_path=Path("unused"),
    seller_id="SELLER-001",
)


def _tools(settings=SETTINGS):
    return {t.name: t for t in build_tools(settings)}


def test_tool_names():
    assert [t.name for t in build_tools(SETTINGS)] == ["get_sales_analytics", "check_inventory_status"]


@pytest.mark.parametrize("name, arg", [("get_sales_analytics", "period"), ("check_inventory_status", "sku")])
def test_schema_hides_seller_id(name, arg):
    # The exact payload bind_tools sends to the model.
    schema = convert_to_openai_tool(_tools()[name])["function"]
    assert list(schema["parameters"]["properties"]) == [arg]
    assert schema["parameters"]["properties"][arg]["description"]
    assert "seller_id" not in json.dumps(schema)


def test_sales_tool():
    result = _tools()["get_sales_analytics"].invoke({"period": "last_week"})
    assert result["ok"] is True
    assert result["data"]["units_sold"] == 904


def test_inventory_unknown_sku():
    result = _tools()["check_inventory_status"].invoke({"sku": "SKU-9999"})
    assert result["error"]["code"] == "UNKNOWN_SKU"


def test_seller_id_is_bound_from_settings():
    tools = _tools(replace(SETTINGS, seller_id="SELLER-999"))
    assert tools["check_inventory_status"].invoke({"sku": "SKU-1001"})["error"]["code"] == "UNKNOWN_SKU"
    assert tools["get_sales_analytics"].invoke({"period": "last_week"})["error"]["code"] == "NO_DATA_FOR_PERIOD"
