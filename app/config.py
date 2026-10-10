"""
app/config.py — Application settings loaded from environment variables.

Uses Pydantic BaseSettings so values can come from:
  1. Environment variables (highest priority)
  2. A .env file in the project root
  3. Defaults defined here (lowest priority)

Database backend: SQLite via aiosqlite (no Docker required).
The database file is created automatically on first startup.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object.  Instantiate via get_settings()."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # silently discard unknown env vars
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_env: str = Field(default="development", description="development | staging | production")
    secret_key: str = Field(default="CHANGE_ME", description="Used for signing tokens / secrets")
    log_level: str = Field(default="INFO")

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # Supports Supabase PostgreSQL (postgresql+asyncpg://...) or SQLite.
    # Reads directly from the DATABASE_URL environment variable.
    database_url: str = Field(
        default="sqlite+aiosqlite:///./database.db",
        description="Async SQLAlchemy database URL. Reads from DATABASE_URL env var. Supports PostgreSQL (Supabase) and local SQLite.",
    )

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------
    rate_limit_submissions_per_minute: int = Field(
        default=10,
        description="Max submission POST requests per IP per sliding 60-second window",
    )

    # ------------------------------------------------------------------
    # Geo-IP (optional — fallback chain skips missing keys)
    # ------------------------------------------------------------------
    ipapi_key: str | None = Field(default=None, description="ipapi.co API key (leave blank to skip)")
    ipstack_key: str | None = Field(default=None, description="ipstack.com API key (leave blank to skip)")

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    Use FastAPI's dependency injection::

        from app.config import get_settings
        from fastapi import Depends

        def my_route(settings: Settings = Depends(get_settings)):
            ...
    """
    return Settings()
