"""Environment-backed settings, loaded once from ``.env``."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-120b"

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # verified: reaches the repo root
DATA_DIR = PROJECT_ROOT / "data"

if not DATA_DIR.is_dir():
    raise ValueError(
        f"DATA_DIR resolved to {DATA_DIR}, which is not a directory: no corpus will "
        "load. Install with `pip install -e .` or run from the repo root."
    )

DEFAULT_LISTINGS_PATH = DATA_DIR / "listings.csv"
DEFAULT_REVIEWS_PATH = DATA_DIR / "reviews.csv"
DEFAULT_POLICY_PATH = DATA_DIR / "policy" / "seller_policy_handbook.md"
DEFAULT_CHROMA_PATH = DATA_DIR / "chroma"
DEFAULT_SELLER_ID = "SELLER-001"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    groq_api_key: str | None
    groq_model: str
    server_port: int
    chroma_path: Path
    seller_id: str


def load_settings() -> Settings:
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "groq").strip().lower(),
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_model=os.getenv("GROQ_MODEL") or DEFAULT_MODEL,
        server_port=int(os.getenv("SERVER_PORT", "7860")),
        chroma_path=Path(os.getenv("CHROMA_PATH") or DEFAULT_CHROMA_PATH),
        seller_id=os.getenv("SELLER_ID") or DEFAULT_SELLER_ID,
    )
