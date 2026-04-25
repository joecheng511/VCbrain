"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    anthropic_api_key: str
    anthropic_model: str
    db_pool_min: int
    db_pool_max: int
    cors_origins: list[str]


def load_settings() -> Settings:
    # CORS_ORIGINS: comma-separated list of allowed origins.
    # Defaults to "*" for local dev. Set to e.g. "https://vcbrain.example.com" in prod.
    raw_origins = os.getenv("CORS_ORIGINS", "*")
    cors_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/dealbrain",
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        db_pool_min=int(os.getenv("DB_POOL_MIN", "2")),
        db_pool_max=int(os.getenv("DB_POOL_MAX", "10")),
        cors_origins=cors_origins,
    )


settings = load_settings()
