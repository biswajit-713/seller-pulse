"""The Gradio chat UI."""

import asyncio
import logging
from typing import Any

import gradio as gr

from seller_pulse.chat import respond
from seller_pulse.config import Settings, load_settings
from seller_pulse.llm import get_client
from seller_pulse.mcp_tools import load_mcp_tools
from seller_pulse.memory import PreferenceStore
from seller_pulse.rag.retrieval import build_retriever
from seller_pulse.router import build_classifier
from seller_pulse.tools import build_memory_tools
from seller_pulse.trace_view import render_trace

DESCRIPTION = "Ask a question in plain English about your seller data."


def build_app(settings: Settings | None = None) -> gr.Blocks:
    settings = settings or load_settings()
    client = get_client(settings)  # built once, reused for every message
    retriever = build_retriever(settings)  # one Chroma client for the process
    store = PreferenceStore(settings.memory_path, settings.seller_id)
    # Analytics over stdio MCP (fails loudly at startup); memory tools stay in-process.
    tools = asyncio.run(load_mcp_tools(settings)) + build_memory_tools(store)
    classify = build_classifier(settings)

    async def handle(message: str, history: list[dict[str, Any]]) -> tuple[str, str]:
        result = await respond(
            message,
            history,
            client=client,
            retriever=retriever,
            tools=tools,
            classify=classify,
            store=store,
        )
        return result.text, render_trace(result)

    # The trace panel is filled through `additional_outputs`, so it is created unrendered and
    # placed below the chat. Gradio 6 passes history as openai-style {"role", "content"} dicts;
    # there is no legacy tuple format to opt out of.
    trace = gr.Markdown(render=False)
    with gr.Blocks(title="Seller Pulse") as demo:
        gr.ChatInterface(
            fn=handle,
            api_name="chat",
            title="Seller Pulse",
            description=DESCRIPTION,
            additional_outputs=[trace],
        )
        with gr.Accordion("Agent trace", open=False):
            trace.render()
    return demo


def launch() -> None:
    logging.basicConfig(level=logging.INFO)  # surfaces chat.py's route + tool-call log
    settings = load_settings()
    build_app(settings).launch(server_port=settings.server_port)
