"""
app/models/database.py — Re-export of app/database.py for backwards compatibility.
"""

from app.database import (  # noqa: F401
    Base,
    engine,
    AsyncSessionLocal,
    get_db,
    get_engine_configuration,
)
