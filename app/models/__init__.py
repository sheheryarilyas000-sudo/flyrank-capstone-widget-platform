"""
app/models/__init__.py

Re-export all ORM models so that importing this package as a side-effect
registers all table metadata on Base before `create_all` is called at startup:

    import app.models  # registers all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
"""

from app.models.submission import Submission  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.widget import Widget  # noqa: F401

# Re-export Base so callers can do `from app.models import Base`
from app.database import Base  # noqa: F401

__all__ = ["Base", "Tenant", "Widget", "Submission"]
