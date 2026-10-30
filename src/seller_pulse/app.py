"""The Gradio chat UI."""

import asyncio
import logging
from typing import Any

import gradio as gr

from seller_pulse.cache import CacheStats, MemoryCache, cached_tools
from seller_pulse.chat import respond
from seller_pulse.config import Settings, load_settings
from seller_pulse.llm import get_client, get_fallback_client
from seller_pulse.mcp_tools import load_mcp_tools
from seller_pulse.memory import PreferenceStore
from seller_pulse.rag.retrieval import build_retriever
from seller_pulse.router import build_classifier
from seller_pulse.tools import build_memory_tools
from seller_pulse.trace_view import render_badges, render_trace

logger = logging.getLogger(__name__)

DESCRIPTION = "Ask a question in plain English about your seller data."


def build_app(settings: Settings | None = None) -> gr.Blocks:
    settings = settings or load_settings()
    client = get_client(settings)  # built once, reused for every message
    fallback = get_fallback_client(settings)  # None unless OPENROUTER_API_KEY is set
    logger.info("caching=%s", "on" if settings.caching else "off")
    embed_cache = (
        MemoryCache(max_entries=settings.cache_embed_max, name="embed")
        if settings.caching
        else None
    )
    retriever = build_retriever(  # one Chroma client for the process
        settings, embed_cache=embed_cache, stats=CacheStats() if embed_cache else None
    )
    store = PreferenceStore(settings.memory_path, settings.seller_id)
    # Analytics over stdio MCP (fails loudly at startup); memory tools stay in-process.
    analytics = asyncio.run(load_mcp_tools(settings))
    if settings.caching:
        analytics = cached_tools(
            analytics,
            MemoryCache(max_entries=settings.cache_tool_max, name="tool"),
            CacheStats(),
            ttl_s=settings.cache_tool_ttl_s,
        )
    tools = analytics + build_memory_tools(store)
    classify = build_classifier(settings)

    async def handle(message: str, history: list[dict[str, Any]]) -> tuple[str, str, str]:
        result = await respond(
            message,
            history,
            client=client,
            retriever=retriever,
            tools=tools,
            classify=classify,
            store=store,
            fallback=fallback,
        )
        return result.text, render_trace(result), render_badges(result)

    # The badges and trace panel are filled through `additional_outputs`, so they are created unrendered and
    # placed below the chat (badges first). Gradio 6 passes history as openai-style {"role", "content"} dicts;
    # there is no legacy tuple format to opt out of.
    badges = gr.Markdown(render=False)
    trace = gr.Markdown(render=False)
    with gr.Blocks(title="Seller Pulse") as demo:
        gr.ChatInterface(
            fn=handle,
            api_name="chat",
            title="Seller Pulse",
            description=DESCRIPTION,
            additional_outputs=[trace, badges],
        )
        badges.render()
        with gr.Accordion("Agent trace", open=False):
            trace.render()
    return demo


def launch() -> None:
    logging.basicConfig(level=logging.INFO)  # surfaces chat.py's route + tool-call log
    settings = load_settings()
    build_app(settings).launch(server_port=settings.server_port)
