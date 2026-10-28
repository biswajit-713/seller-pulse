# Request workflow

How one chat turn moves through SellerPulse and back to the seller. Source of truth is the code:
`app.py:handle` → `chat.py:respond` → `agent.py:run_agent`. Rendered by GitHub; any Mermaid viewer works.

```mermaid
flowchart TD
    User([Seller types a question]) --> UI["app.py · Gradio ChatInterface<br/>handle(message, history)"]
    UI --> Sanitize["sanitize.py<br/>clean the message"]
    Sanitize --> Empty{"Empty after<br/>cleaning?"}
    Empty -- yes --> EmptyReply["Canned reply:<br/>'Type a question about your seller data…'<br/>no model call"]
    Empty -- no --> Msgs["chat.py:to_messages<br/>Gradio history → role/content messages"]

    Msgs --> Par{{"asyncio.gather · concurrent"}}

    subgraph Parallel["Route + retrieve (cost ≈ max of the two)"]
        direction LR
        Classify["router.py:classify_query<br/>small router model, strict JSON schema, 4s timeout<br/>→ routes: data / reviews / policy / memory"]
        FailOpen["Error or timeout<br/>→ fail open to ALL routes"]
        Retrieve["rag/retrieval.py:retrieve<br/>Chroma vector search"]
        EmbCache[("Embedding cache<br/>CACHING=on")]
        Classify -.-> FailOpen
        Retrieve <-.-> EmbCache
    end

    Par --> Classify
    Par --> Retrieve

    Classify --> Routes["RouteDecision.routes"]
    Retrieve --> Docs["Retrieved chunks"]

    Routes --> ToolsFor["router.py:tools_for(routes)<br/>data → get_sales_analytics, check_inventory_status,<br/>find_listing, list_low_stock<br/>memory → save_preference, list_preferences<br/>reviews / policy → no tools"]
    Routes --> Prompt
    Docs --> Ctx["rag/context.py:render_context<br/>context_block, rendered once"]
    Ctx --> Prompt["Assemble system prompt<br/>prompts.py:build_system_prompt(routes): CORE + data/reviews/policy modules<br/>+ context_block<br/>+ render_preferences (every turn, any route)"]
    Prefs[("memory.py:PreferenceStore<br/>JSON per seller, re-read each turn")] --> Prompt

    Prompt --> Agent
    ToolsFor --> Agent

    subgraph Loop["agent.py:run_agent · max 5 model calls"]
        Agent["Call model<br/>ChatGroq, bound to routed tools only"]
        Agent --> Wants{"Tool calls<br/>requested?"}
        Wants -- yes --> RunTool["_run_tool for each call<br/>errors become an error envelope<br/>fed back to the model"]
        RunTool --> Record["Record ToolCallRecord<br/>name, args, result, cached, latency_ms"]
        Record --> Agent
        Wants -- no --> Answer["Plain-text answer"]
        Agent -. "5 steps, still asking for tools" .-> Fallback["FALLBACK_TEXT<br/>'I couldn't finish pulling the data…'"]
    end

    RunTool <--> ToolCache[("cache.py · tool-result cache<br/>key = tool + args, TTL<br/>analytics only")]
    ToolCache <--> MCP["mcp_server.py · stdio MCP<br/>get_sales_analytics, check_inventory_status,<br/>find_listing, list_low_stock<br/>→ sales.py / inventory.py"]
    RunTool <--> MemTools["In-process memory tools<br/>never cached"]
    MemTools <--> Prefs

    Answer --> Guard
    Fallback --> Guard
    Record -. "this turn's tool calls" .-> Guard

    Guard["guardrails.py:check_output · no model call<br/>checks answer vs tool calls, context_block,<br/>seller message, saved preferences"]
    Guard --> Annotate["guardrails.py:annotate<br/>unsourced figures/ids and publish claims<br/>→ caution lines appended, never blocked<br/>draft-pending, policy-refusal → status only"]
    Annotate --> Result["ChatResult<br/>text, trace, routes, route_fallback,<br/>preferences, guardrail report"]

    Result --> View["trace_view.py<br/>render_badges: guardrail, draft pending, cache hit/miss<br/>render_trace: routes, tool calls, preferences, guardrail"]
    View --> Out["Gradio outputs: (text, trace_markdown, badges_markdown)"]
    EmptyReply --> Out
    Out --> Seen([Seller sees answer, badges,<br/>and the 'Agent trace' accordion])
```

## Notes

- **Concurrency:** the classifier and retrieval run together; retrieval is unconditional, so a routing miss never loses context.
- **Fail-open:** a classifier error or 4s timeout routes to all routes (`route_fallback=True`), so nothing is silently dropped.
- **Guardrails annotate, not block:** the seller always gets the answer, with caution lines where a figure or id isn't backed by this turn's evidence.
- **Caching** (`CACHING=on`, app only): query embeddings in retrieval and analytics tool results in the tool loop. Memory tools are never cached. Cache hits show as "(cached)" in the trace.
- **Startup, not per turn:** `app.py:build_app` builds the model client, retriever, preference store, MCP tool list and classifier once.
