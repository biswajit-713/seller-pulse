# Observability: Langfuse tracing (#26)

One Langfuse trace per chat turn. Code: `tracing.py` (the only module importing `langfuse`),
called from `chat.py:respond`. Off unless configured; a Langfuse failure never breaks a turn.

## What is traced

Trace `turn` (trace metadata `turn_ms`, grouped by Gradio `session_hash` as the Langfuse
session) with these children:

| Event | Observation (type) | Metadata |
|---|---|---|
| Router | `route` (SPAN) | `routes`, `fallback`, `latency_ms` |
| Retrieval | `retrieval` (RETRIEVER) | `mode`, `count`, `hits` (id + distance), `embed_cache_hits/misses` |
| Tool call | one per call, named after the tool (TOOL); level ERROR when `ok` is false | input = args; `ok`, `error_code`, `cached`, `latency_ms` |
| Guardrail | `guardrail` (GUARDRAIL) | `triggered`, `unverified_figures`, `ungrounded_ids`, `draft_pending`, `publish_claim`, `policy_refusal`, `policy_clauses` |
| LLM calls | `ChatGroq` (GENERATION) etc. | via the LangChain callback handler |

Scores on the trace (numeric): `tool_failures`, `tool_calls`, `guardrail_triggered`.

Event spans are written after the fact, so their own duration is ~0; real timings are in
`latency_ms` / `turn_ms` metadata. The Agent trace panel in the UI (`trace_view.py`) is a
separate view.

## Find a trace

Each turn logs `turn_ms=<n> trace_id=<id>` (INFO, `chat.py`). In Langfuse Cloud, open
Tracing and search that id. The same id is `ChatResult.trace_id`.

## Config

`.env`: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (US project:
`https://us.cloud.langfuse.com`; blank → SDK default EU), `TRACING=on|off` (default on).
Tracing is also off when either key is blank. Off → `NO_TRACE`, no `langfuse` import, no
network. Startup logs `tracing=on|off`.

## Evidence (2026-11-04, live app, Groq)

Exports in `docs/traces/` (route/retrieval/tool/guardrail/turn spans and scores; LLM
generations omitted, keys stripped):

| Scenario | trace_id | File | Shows |
|---|---|---|---|
| "How were my sales last week?" asked twice, second turn | `e2d04a241ee5dd462a5388ae2df70393` | `trace-cache-hit.json` | all event types in one trace; tool `cached=true`, `latency_ms=1`; scores 0/1/0; embed cache hits=2 |
| SKU-9999 stock status | `689eb94e23f18ce2114397c3d00bb1a0` | `trace-tool-failure.json` | `check_inventory_status` level ERROR, `UNKNOWN_SKU`; `tool_failures=1` |
| SQ-06 free gift for a 5-star review | `645bbce3665f905a20b12c966826af58` | `trace-policy-refusal.json` | `policy_refusal`; `guardrail_triggered=1` |

First sales turn (cold): `turn_ms=9043 trace_id=7ed398a38701dd093347c489f352c590`, tool
`cached=False ms=502`.

Export note: this org can't use the legacy `/api/public/traces` or `/api/public/v2/scores`
(`LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION`). Use
`GET /api/public/v2/observations?traceId=…&fromStartTime=…&toStartTime=…&fields=core,basic,io,metadata`
and `GET /api/public/v3/scores?traceId=…`.
