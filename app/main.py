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
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.routers import admin, auth, dashboard, embed, submissions, tenant, widgets
from app.utils.limiter import limiter

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""

    application = FastAPI(
        title="Nova Leads API",
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
    # Production-Ready CORS
    # Reads ALLOWED_ORIGINS / CORS_ORIGINS from environment variables.
    # Allows comma-separated list of origins, falling back to ["*"] only
    # if explicitly set or unconfigured for embed flexibility.
    # ------------------------------------------------------------------
    raw_cors = os.getenv("ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS") or "*"
    if raw_cors.strip() == "*":
        cors_origins = ["*"]
        allow_creds = False
    else:
        cors_origins = [orig.strip() for orig in raw_cors.split(",") if orig.strip()]
        allow_creds = True

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_creds,
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

        logger.info("Starting Nova Leads Platform (env=%s)", settings.app_env)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

                # PostgreSQL and SQLite compatible column check and migration
                from sqlalchemy import inspect, text

                def check_and_add_columns(sync_conn):
                    inspector = inspect(sync_conn)
                    existing_tables = inspector.get_table_names()
                    migrations = [
                        ("tenants", "email", "VARCHAR(255)"),
                        ("tenants", "full_name", "VARCHAR(255)"),
                        ("tenants", "website_url", "VARCHAR(500)"),
                        ("tenants", "industry", "VARCHAR(100)"),
                        ("tenants", "phone_number", "VARCHAR(50)"),
                        ("submissions", "phone", "VARCHAR(50)"),
                        ("submissions", "lead_company", "VARCHAR(255)"),
                    ]
                    for table, column, col_type in migrations:
                        if table in existing_tables:
                            cols = [c["name"] for c in inspector.get_columns(table)]
                            if column not in cols:
                                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))

                await conn.run_sync(check_and_add_columns)
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
    application.include_router(auth.router)
    application.include_router(tenant.router)
    application.include_router(widgets.router)
    application.include_router(embed.router)
    application.include_router(submissions.router)
    application.include_router(dashboard.router)
    application.include_router(admin.router)

    # ------------------------------------------------------------------
    # Static files & SPA Dashboard Mounts
    # ------------------------------------------------------------------
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dashboard_dir = os.path.join(BASE_DIR, "dashboard")
    test_site_dir = os.path.join(BASE_DIR, "test_site")
    sample_store_file = os.path.join(BASE_DIR, "sample_client_store.html")
    admin_dashboard_file = os.path.join(BASE_DIR, "admin_dashboard.html")

    if os.path.isdir(dashboard_dir):
        application.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
    if os.path.isdir(test_site_dir):
        application.mount("/test_site", StaticFiles(directory=test_site_dir, html=True), name="test_site")

    if os.path.isfile(sample_store_file):
        @application.get("/sample-store", include_in_schema=False)
        @application.get("/sample_client_store.html", include_in_schema=False)
        async def serve_sample_client_store():
            """Serve the mock client store website for cross-origin embed testing."""
            return FileResponse(sample_store_file, media_type="text/html")

    if os.path.isfile(admin_dashboard_file):
        @application.get("/admin", include_in_schema=False)
        @application.get("/admin_dashboard.html", include_in_schema=False)
        async def serve_admin_dashboard():
            """Serve the isolated Super Admin operations portal."""
            return FileResponse(admin_dashboard_file, media_type="text/html")

    # ------------------------------------------------------------------
    # Built-in routes
    # ------------------------------------------------------------------
    @application.get("/health", tags=["Ops"])
    async def health_check() -> dict:
        """Liveness probe — returns 200 immediately."""
        return {"status": "ok", "version": application.version}

    @application.get("/", include_in_schema=False)
    async def root_redirect():
        """Redirect root requests to the Dashboard SPA if available."""
        if os.path.isfile(os.path.join(dashboard_dir, "index.html")):
            return RedirectResponse(url="/dashboard/")
        return {"status": "ok", "docs": "/docs"}

    # ------------------------------------------------------------------
    # Swagger & OpenAPI Security Polish
    # ------------------------------------------------------------------
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema
        openapi_schema = get_openapi(
            title="Nova Leads Platform API",
            version="1.0.0",
            description=(
                "Production Multi-Tenant B2B SaaS API for embeddable lead-capture widgets.\n\n"
                "### Multi-Tenant Isolation & Authentication\n"
                "All tenant endpoints enforce strict data isolation (`tenant_id`) and authenticate via:\n"
                "- **`X-Api-Key`** header: Your workspace API key (`nova_live_...`)\n"
                "- **`Authorization`** header: `Bearer <nova_live_...>`\n\n"
                "No tenant can view or mutate another workspace's leads or widgets."
            ),
            routes=application.routes,
        )
        openapi_schema["components"] = openapi_schema.get("components", {})
        openapi_schema["components"]["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Api-Key",
                "description": "Tenant API Key (e.g., nova_live_...)",
            },
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "APIKey",
                "description": "Bearer token using your Tenant API Key",
            },
            "AdminKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Admin-Key",
                "description": "Master Super Admin Key (ADMIN_SECRET_KEY)",
            },
        }
        openapi_schema["security"] = [{"ApiKeyAuth": []}, {"BearerAuth": []}, {"AdminKeyAuth": []}]
        application.openapi_schema = openapi_schema
        return application.openapi_schema

    application.openapi = custom_openapi

    return application


# ---------------------------------------------------------------------------
# Module-level app instance (consumed by uvicorn)
# ---------------------------------------------------------------------------
app = create_app()
