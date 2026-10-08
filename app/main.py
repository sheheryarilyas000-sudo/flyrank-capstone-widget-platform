"""
app/main.py — FastAPI application entry point.

This module:
  - Creates and configures the FastAPI application instance
  - Mounts CORSMiddleware (allow_origins=["*"] for the public widget embed)
  - Wires slowapi rate-limiter state and its 429 exception handler
  - Registers startup/shutdown lifecycle hooks (schema creation, engine disposal)
  - Registers all API routers
  - Exposes a /health liveness endpoint

Run with:
    uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.routers import dashboard, embed, submissions, widgets
from app.utils.limiter import limiter

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""

    application = FastAPI(
        title="Flyrank Widget Platform API",
        description=(
            "B2B SaaS backend for embeddable lead-capture widgets. "
            "See /docs for interactive API documentation."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # Rate limiter — attach singleton to app state so slowapi can find it.
    # The custom exception handler returns our standard JSON error shape
    # instead of slowapi's default plain-text "Rate limit exceeded" string.
    # ------------------------------------------------------------------
    application.state.limiter = limiter

    async def _custom_rate_limit_handler(
        request: Request, exc: RateLimitExceeded
    ) -> JSONResponse:
        """Return 429 in our standard error envelope."""
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": "rate_limit_exceeded",
                "detail": f"Too many requests. Limit: {exc.detail}.",
            },
        )

    application.add_exception_handler(RateLimitExceeded, _custom_rate_limit_handler)

    # ------------------------------------------------------------------
    # CORS
    # The embed script runs on arbitrary third-party domains, so we must
    # allow all origins.  allow_credentials must be False when
    # allow_origins=["*"] (browser security constraint).
    # ------------------------------------------------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Lifecycle events
    # ------------------------------------------------------------------
    @application.on_event("startup")
    async def on_startup() -> None:
        """Create all database tables on first boot (idempotent on restarts)."""
        import app.models  # noqa: F401 — registers all ORM tables on Base.metadata
        from app.database import Base, engine

        logger.info("Starting Flyrank Widget Platform (env=%s)", settings.app_env)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema ready (tables created / verified).")
        except Exception as exc:  # noqa: BLE001
            logger.error("Database startup FAILED: %s", exc)

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        from app.database import engine

        await engine.dispose()
        logger.info("Database engine disposed. Shutdown complete.")

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    application.include_router(widgets.router)
    application.include_router(embed.router)
    application.include_router(submissions.router)
    application.include_router(dashboard.router)

    # ------------------------------------------------------------------
    # Built-in routes
    # ------------------------------------------------------------------
    @application.get("/health", tags=["Ops"])
    async def health_check() -> dict:
        """Liveness probe — returns 200 immediately."""
        return {"status": "ok", "version": application.version}

    return application


# ---------------------------------------------------------------------------
# Module-level app instance (consumed by uvicorn)
# ---------------------------------------------------------------------------
app = create_app()
