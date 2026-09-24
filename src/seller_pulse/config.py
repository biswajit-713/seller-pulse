"""Environment-backed settings, loaded once from ``.env``."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    anthropic_api_key: str | None
    anthropic_model: str
    server_port: int


def load_settings() -> Settings:
    # "fake" by default so a fresh clone runs without an API key.
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "fake").strip().lower(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL,
        server_port=int(os.getenv("SERVER_PORT", "7860")),
    )
