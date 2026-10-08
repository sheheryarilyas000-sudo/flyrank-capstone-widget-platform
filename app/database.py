"""
app/database.py — Async SQLAlchemy engine, session factory, and base class.

Backend: SQLite via aiosqlite (no Docker or PostgreSQL required).
The database file (database.db) is created automatically the first time
the application starts, via `Base.metadata.create_all` in main.py's
startup lifecycle hook.

All ORM models inherit from `Base`.
All route handlers receive an async DB session via the `get_db` dependency.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# SQLite-specific notes:
#   - `check_same_thread=False` is required because SQLAlchemy's async engine
#     may hand connections between threads internally.
#   - Connection pooling is disabled (StaticPool / NullPool not needed for
#     aiosqlite; SQLAlchemy handles this automatically for SQLite).
#   - echo=True in development logs every SQL statement to stdout.
engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    connect_args={"check_same_thread": False},
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
