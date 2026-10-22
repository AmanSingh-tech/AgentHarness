"""Runtime configuration from environment variables (optionally via .env)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines; existing env vars win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class Settings(BaseModel):
    db_url: str = "sqlite:///agentguard.db"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            db_url=os.environ.get("AGENTGUARD_DB_URL", cls.model_fields["db_url"].default),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        )
