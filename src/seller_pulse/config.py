"""Environment-backed settings, loaded once from ``.env``."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-120b"
# Eval judge: a different vendor from the agent so it isn't grading its own family.
# Kimi K2 and qwen3-32b were both off Groq's model list as of 2026-10-05 (see ev-00).
DEFAULT_JUDGE_MODEL = "qwen/qwen3.8-27b"
# Same vendor-different-from-agent rule on OpenRouter (not checked against the live catalogue).
DEFAULT_OPENROUTER_JUDGE_MODEL = "qwen/qwen3-32b"
# Query classifier (rt-04). Chosen by rt-05: 31/31 routes ×3 runs, and it keeps the router off
# the agent model's per-model Groq token limits (see plan/rt-00-overview.md).
DEFAULT_ROUTER_MODEL = "openai/gpt-oss-20b"
# OpenRouter: the agent model when LLM_PROVIDER=openrouter, else the 429 fallback (same gpt-oss
# family, paid). The router default above is also a valid OpenRouter id.
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-120b"

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # verified: reaches the repo root
DATA_DIR = PROJECT_ROOT / "data"

if not DATA_DIR.is_dir():
    raise ValueError(
        f"DATA_DIR resolved to {DATA_DIR}, which is not a directory: no corpus will "
        "load. Install with `pip install -e .` or run from the repo root."
    )

DEFAULT_LISTINGS_PATH = DATA_DIR / "listings.csv"
DEFAULT_REVIEWS_PATH = DATA_DIR / "reviews.csv"
DEFAULT_SALES_PATH = DATA_DIR / "sales.csv"
DEFAULT_POLICY_PATH = DATA_DIR / "policy" / "seller_policy_handbook.md"
DEFAULT_CHROMA_PATH = DATA_DIR / "chroma"
DEFAULT_MEMORY_PATH = DATA_DIR / "memory"
DEFAULT_CACHE_EMBED_MAX = 1024
DEFAULT_CACHE_TOOL_MAX = 256
DEFAULT_CACHE_TOOL_TTL_S = 300
DEFAULT_RETRIEVAL_CASES_PATH = DATA_DIR / "synthetic_queries" / "retrieval_cases.jsonl"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    groq_api_key: str | None
    groq_model: str
    server_port: int
    chroma_path: Path
    seller_id: str
    # Set → used as the agent model's fallback when Groq answers 429 (llm/factory.py).
    openrouter_api_key: str | None = None
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    judge_model: str = DEFAULT_JUDGE_MODEL
    router_model: str = DEFAULT_ROUTER_MODEL
    # ROUTING=off (rt-07's revert path): no classifier call, every module and every tool.
    routing: bool = True
    # Seller preference store (w2-12): one JSON file per seller under this directory.
    memory_path: Path = DEFAULT_MEMORY_PATH
    # CACHING=off: no embedding or tool-result caching (for before/after comparisons).
    caching: bool = True
    cache_embed_max: int = DEFAULT_CACHE_EMBED_MAX
    cache_tool_max: int = DEFAULT_CACHE_TOOL_MAX
    cache_tool_ttl_s: float = DEFAULT_CACHE_TOOL_TTL_S
    # INPUT_RAILS=on: NeMo input rail (w4-09) blocks jailbreaks/policy-violating asks before the
    # agent runs. Off by default until the eval shows no regression.
    input_rails: bool = False
    # TRACING=off: no Langfuse traces. Tracing is also off when either key is blank.
    tracing: bool = True
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None  # None → the SDK default (Langfuse Cloud EU)

    @property
    def agent_model(self) -> str:
        return self.openrouter_model if self.llm_provider == "openrouter" else self.groq_model

    @property
    def api_key_name(self) -> str:
        return "OPENROUTER_API_KEY" if self.llm_provider == "openrouter" else "GROQ_API_KEY"

    @property
    def llm_api_key(self) -> str | None:
        return self.openrouter_api_key if self.llm_provider == "openrouter" else self.groq_api_key

    @property
    def tracing_active(self) -> bool:
        return self.tracing and bool(self.langfuse_public_key and self.langfuse_secret_key)


def _load_on_off(name: str, default: str = "on") -> bool:
    value = (os.getenv(name) or default).strip().lower()
    if value not in ("on", "off"):
        raise ValueError(f"{name} must be 'on' or 'off', got {value!r}.")
    return value == "on"


def _positive(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive number, got {raw!r}.") from None
    if not value > 0:  # also rejects nan
        raise ValueError(f"{name} must be a positive number, got {raw!r}.")
    return value


def load_settings() -> Settings:
    # Stand-in for auth (prototype only): the tenant comes from env, not a login.
    # No default: a fallback tenant would silently serve one seller's data to a
    # misconfigured process. See docs/tools.md §1.
    seller_id = (os.getenv("SELLER_ID") or "").strip()
    if not seller_id:
        raise ValueError("SELLER_ID is not set. Set it in .env (e.g. SELLER_ID=SELLER-001).")
    llm_provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if llm_provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
        raise ValueError("LLM_PROVIDER=openrouter needs OPENROUTER_API_KEY in .env.")
    return Settings(
        llm_provider=llm_provider,
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_model=os.getenv("GROQ_MODEL") or DEFAULT_MODEL,
        server_port=int(os.getenv("SERVER_PORT", "7860")),
        chroma_path=Path(os.getenv("CHROMA_PATH") or DEFAULT_CHROMA_PATH),
        seller_id=seller_id,
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        openrouter_model=os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL,
        judge_model=os.getenv("JUDGE_MODEL")
        or (DEFAULT_OPENROUTER_JUDGE_MODEL if llm_provider == "openrouter" else DEFAULT_JUDGE_MODEL),
        router_model=os.getenv("ROUTER_MODEL") or DEFAULT_ROUTER_MODEL,
        routing=_load_on_off("ROUTING"),
        memory_path=Path(os.getenv("MEMORY_PATH") or DEFAULT_MEMORY_PATH),
        caching=_load_on_off("CACHING"),
        cache_embed_max=int(_positive("CACHE_EMBED_MAX", DEFAULT_CACHE_EMBED_MAX)),
        cache_tool_max=int(_positive("CACHE_TOOL_MAX", DEFAULT_CACHE_TOOL_MAX)),
        cache_tool_ttl_s=_positive("CACHE_TOOL_TTL_S", DEFAULT_CACHE_TOOL_TTL_S),
        input_rails=_load_on_off("INPUT_RAILS", "off"),
        tracing=_load_on_off("TRACING"),
        langfuse_public_key=(os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip() or None,
        langfuse_secret_key=(os.getenv("LANGFUSE_SECRET_KEY") or "").strip() or None,
        langfuse_host=(os.getenv("LANGFUSE_HOST") or "").strip() or None,
    )
