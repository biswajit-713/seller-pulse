"""The Gradio chat UI."""

import logging
from functools import partial
from typing import Any

import gradio as gr

from seller_pulse.chat import respond
from seller_pulse.config import Settings, load_settings
from seller_pulse.llm import get_client, get_router_client
from seller_pulse.rag.retrieval import build_retriever
from seller_pulse.router import classify_query
from seller_pulse.tools import build_tools

DESCRIPTION = "Ask a question in plain English about your seller data."


def build_app(settings: Settings | None = None) -> gr.Blocks:
    settings = settings or load_settings()
    client = get_client(settings)  # built once, reused for every message
    retriever = build_retriever(settings)  # one Chroma client for the process
    tools = build_tools(settings)
    classify = partial(classify_query, get_router_client(settings).chat_model)

    async def handle(message: str, history: list[dict[str, Any]]) -> str:
        result = await respond(
            message, history, client=client, retriever=retriever, tools=tools, classify=classify
        )
        return result.text

    # Gradio 6 passes history as openai-style {"role", "content"} dicts; there is
    # no legacy tuple format to opt out of.
    return gr.ChatInterface(
        fn=handle,
        api_name="chat",
        title="Seller Pulse",
        description=DESCRIPTION,
    )


def launch() -> None:
    logging.basicConfig(level=logging.INFO)  # surfaces chat.py's route + tool-call log
    settings = load_settings()
    build_app(settings).launch(server_port=settings.server_port)
