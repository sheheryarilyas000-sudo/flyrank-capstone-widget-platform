"""
app/database.py — Async SQLAlchemy engine, session factory, and base class.

Backend: SQLite via aiosqlite (no Docker or PostgreSQL required).
The database file (database.db) is created automatically the first time
the application starts, via `Base.metadata.create_all` in main.py's
startup lifecycle hook.

All ORM models inherit from `Base`.
All route handlers receive an async DB session via the `get_db` dependency.
"""

import os
import logging
import re
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_engine_configuration(raw_url: str) -> tuple[str, dict, dict]:
    """Normalize DATABASE_URL and configure driver-specific engine parameters.

    Supports:
      1. Serverless PostgreSQL (Supabase / Neon): handles 'postgres://' and 'postgresql://' prefixes,
         normalizes to 'postgresql+asyncpg://', configures SSL and serverless pooling.
      2. Local SQLite fallback (aiosqlite): only if DATABASE_URL is not set.
    """
    url = raw_url

    # Convert standard PostgreSQL URLs to asyncpg dialect
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    connect_args: dict = {}
    engine_kwargs: dict = {
        "echo": (settings.app_env == "development"),
        "pool_pre_ping": True,  # Discards stale connections on serverless / Supabase pooler
    }

    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    else:
        # PostgreSQL (Supabase / Neon / AWS RDS)
        # Strip sslmode= from query string if present because asyncpg expects ssl in connect_args
        if "sslmode=" in url:
            url = re.sub(r"([?&])sslmode=[^&]+(&?)", r"\1\2", url).rstrip("?&")
            connect_args["ssl"] = "require"
        elif any(host in url for host in ("supabase.co", "pooler.supabase.com", "neon.tech")):
            connect_args["ssl"] = "require"

        # Serverless connection pool tuning
        engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
        engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        engine_kwargs["pool_recycle"] = 300

    return url, connect_args, engine_kwargs


# ---------------------------------------------------------------------------
# Engine
# Priority: os.getenv("DATABASE_URL") -> POSTGRES_URL -> SUPABASE_DB_URL -> settings.database_url
# ---------------------------------------------------------------------------
raw_db_url = (
    os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("SUPABASE_DB_URL")
    or getattr(settings, "database_url", "sqlite+aiosqlite:///./database.db")
)
db_url, connect_args, engine_kwargs = get_engine_configuration(raw_db_url)

engine = create_async_engine(
    db_url,
    connect_args=connect_args,
    **engine_kwargs,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep attributes accessible after commit
)

# ---------------------------------------------------------------------------
# Declarative Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    All models that inherit from this class will have their tables created
    automatically via `Base.metadata.create_all(engine)` on startup.
    """
    pass


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a scoped async database session.

    Usage::

        from app.database import get_db
        from fastapi import Depends
        from sqlalchemy.ext.asyncio import AsyncSession

        async def my_route(db: AsyncSession = Depends(get_db)):
            result = await db.execute(...)

    The session is automatically committed on success and rolled back on any
    unhandled exception, then closed in the finally block.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
