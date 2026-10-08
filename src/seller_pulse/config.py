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
# Query classifier (rt-04). Provisional: rt-05 confirms it or switches to gpt-oss-120b.
DEFAULT_ROUTER_MODEL = "openai/gpt-oss-20b"

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
DEFAULT_RETRIEVAL_CASES_PATH = DATA_DIR / "synthetic_queries" / "retrieval_cases.jsonl"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    groq_api_key: str | None
    groq_model: str
    server_port: int
    chroma_path: Path
    seller_id: str
    judge_model: str = DEFAULT_JUDGE_MODEL
    router_model: str = DEFAULT_ROUTER_MODEL


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
        judge_model=os.getenv("JUDGE_MODEL") or DEFAULT_JUDGE_MODEL,
        router_model=os.getenv("ROUTER_MODEL") or DEFAULT_ROUTER_MODEL,
    )
