import json
from pathlib import Path

import gradio as gr
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from seller_pulse import app
from seller_pulse.agent import run_agent
from seller_pulse.config import Settings
from seller_pulse.memory import PREFERENCE_KEYS, PreferenceStore
from seller_pulse.tools import build_memory_tools
from tests.test_agent_loop import ScriptedChatModel

SELLER = "SELLER-001"


def _tools(tmp_path):
    return {t.name: t for t in build_memory_tools(PreferenceStore(tmp_path, SELLER))}


def test_key_is_an_enum_in_the_schema(tmp_path):
    params = convert_to_openai_tool(_tools(tmp_path)["save_preference"])["function"]["parameters"]
    assert params["properties"]["key"]["enum"] == list(PREFERENCE_KEYS)
    assert set(params["required"]) == {"key", "value"}


def test_save_writes_file(tmp_path):
    result = _tools(tmp_path)["save_preference"].invoke(
        {"key": "reply_tone", "value": "short and warm, no emojis"}
    )
    assert result == {
        "ok": True,
        "data": {"key": "reply_tone", "value": "short and warm, no emojis", "previous_value": None},
    }
    on_disk = json.loads((tmp_path / f"{SELLER}.json").read_text())
    assert on_disk["reply_tone"]["value"] == "short and warm, no emojis"


def test_resave_returns_previous_value(tmp_path):
    save = _tools(tmp_path)["save_preference"]
    save.invoke({"key": "restock_threshold", "value": "5"})
    result = save.invoke({"key": "restock_threshold", "value": "3"})
    assert result["data"] == {"key": "restock_threshold", "value": "3", "previous_value": "5"}


def test_list_returns_all(tmp_path):
    tools = _tools(tmp_path)
    assert tools["list_preferences"].invoke({}) == {"ok": True, "data": {"preferences": {}}}

    tools["save_preference"].invoke({"key": "reply_tone", "value": "short and warm, no emojis"})
    tools["save_preference"].invoke({"key": "restock_threshold", "value": "5"})
    tools["save_preference"].invoke({"key": "restock_threshold", "value": "3"})

    prefs = tools["list_preferences"].invoke({})["data"]["preferences"]
    assert {k: p["value"] for k, p in prefs.items()} == {
        "reply_tone": "short and warm, no emojis",
        "restock_threshold": "3",
    }


def test_invalid_threshold_is_an_error_envelope(tmp_path):
    result = _tools(tmp_path)["save_preference"].invoke({"key": "restock_threshold", "value": "a few"})
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_PREFERENCE"
    assert not (tmp_path / f"{SELLER}.json").exists()


async def test_agent_loop_records_save_call(tmp_path):
    call = {"name": "save_preference", "args": {"key": "notification_cadence", "value": "every Friday"}, "id": "c1"}
    model = ScriptedChatModel([AIMessage(content="", tool_calls=[call]), AIMessage(content="Saved.")])
    result = await run_agent(
        model,
        system="sys",
        messages=[{"role": "user", "content": "Notify me every Friday."}],
        tools=build_memory_tools(PreferenceStore(tmp_path, SELLER)),
    )
    assert result.text == "Saved."
    [record] = result.tool_calls
    assert (record.name, record.args) == ("save_preference", call["args"])
    assert record.result["data"]["value"] == "every Friday"
    assert PreferenceStore(tmp_path, SELLER).get_all()["notification_cadence"].value == "every Friday"


def test_build_app_merges_memory_tools(tmp_path, monkeypatch):
    seen = {}

    async def fake_mcp_tools(settings):
        return ["mcp-tool"]

    def fake_build_memory_tools(store):
        seen["store"] = store
        return ["memory-tool"]

    monkeypatch.setattr(app, "get_client", lambda s: object())
    monkeypatch.setattr(app, "build_retriever", lambda s: object())
    monkeypatch.setattr(app, "build_classifier", lambda s: object())
    monkeypatch.setattr(app, "load_mcp_tools", fake_mcp_tools)
    monkeypatch.setattr(app, "build_memory_tools", fake_build_memory_tools)

    settings = Settings(
        llm_provider="groq",
        groq_api_key=None,
        groq_model="test-model",
        server_port=7860,
        chroma_path=Path("unused"),
        seller_id=SELLER,
        memory_path=tmp_path,
    )
    demo = app.build_app(settings)
    assert isinstance(demo, gr.Blocks)
    assert isinstance(seen["store"], PreferenceStore)
    assert any(fn.api_name == "chat" for fn in demo.fns.values())  # the Gradio API surface
