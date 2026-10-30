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
# Query classifier (rt-04). Chosen by rt-05: 31/31 routes ×3 runs, and it keeps the router off
# the agent model's per-model Groq token limits (see plan/rt-00-overview.md).
DEFAULT_ROUTER_MODEL = "openai/gpt-oss-20b"
# OpenRouter: the 429 fallback for the agent model (same gpt-oss family, free tier).
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-120b:free"

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


def _load_routing() -> bool:
    value = (os.getenv("ROUTING") or "on").strip().lower()
    if value not in ("on", "off"):
        raise ValueError(f"ROUTING must be 'on' or 'off', got {value!r}.")
    return value == "on"


def _load_caching() -> bool:
    value = (os.getenv("CACHING") or "on").strip().lower()
    if value not in ("on", "off"):
        raise ValueError(f"CACHING must be 'on' or 'off', got {value!r}.")
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
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "groq").strip().lower(),
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_model=os.getenv("GROQ_MODEL") or DEFAULT_MODEL,
        server_port=int(os.getenv("SERVER_PORT", "7860")),
        chroma_path=Path(os.getenv("CHROMA_PATH") or DEFAULT_CHROMA_PATH),
        seller_id=seller_id,
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        openrouter_model=os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL,
        judge_model=os.getenv("JUDGE_MODEL") or DEFAULT_JUDGE_MODEL,
        router_model=os.getenv("ROUTER_MODEL") or DEFAULT_ROUTER_MODEL,
        routing=_load_routing(),
        memory_path=Path(os.getenv("MEMORY_PATH") or DEFAULT_MEMORY_PATH),
        caching=_load_caching(),
        cache_embed_max=int(_positive("CACHE_EMBED_MAX", DEFAULT_CACHE_EMBED_MAX)),
        cache_tool_max=int(_positive("CACHE_TOOL_MAX", DEFAULT_CACHE_TOOL_MAX)),
        cache_tool_ttl_s=_positive("CACHE_TOOL_TTL_S", DEFAULT_CACHE_TOOL_TTL_S),
    )
