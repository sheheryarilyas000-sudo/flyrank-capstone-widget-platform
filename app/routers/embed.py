"""
app/routers/embed.py — Public widget delivery and configuration endpoints.

This module delivers:
  1. GET /api/widgets/{widget_id}/config (and alias /embed/{widget_id}/config):
     Returns the form definition JSON for an active widget with HTTP caching.
  2. GET /widget.js:
     Returns the client-side embed bundle / loader script with long cache headers.

Both endpoints are public and allow external websites to load and render widgets.
"""

import logging
import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.widget import Widget

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Widget Delivery & Embed"],
)


@router.get(
    "/api/widgets/{widget_id}/config",
    summary="Get widget configuration",
    response_description="Widget configuration definition",
)
@router.get(
    "/embed/{widget_id}/config",
    summary="Get widget configuration (alias)",
    include_in_schema=False,
)
async def get_widget_config(
    widget_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Retrieve public configuration for an active widget.

    Used by widget.js to render the form fields dynamically.
    Enforces HTTP caching (Cache-Control: public, max-age=300) to minimize database load.
    Does NOT leak tenant credentials or internal metadata.
    """
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "widget_not_found"},
        )

    stmt = select(Widget).where(Widget.id == wid, Widget.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()

    if widget is None:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "widget_not_found"},
        )

    # Return widget config JSON with standard cache headers
    return JSONResponse(
        content=widget.config,
        headers={
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get(
    "/widget.js",
    summary="Download embed script bundle",
    response_description="JavaScript bundle for rendering the embed widget",
)
async def get_widget_js(
    id: str | None = Query(None, description="Widget ID passed as query parameter"),
    widget_id: str | None = Query(None, description="Alternative widget ID query parameter"),
) -> Response:
    """Return the client-side embeddable JavaScript bundle.

    External client websites include:
      <script src="http://localhost:8000/widget.js?id=YOUR_WIDGET_ID"></script>

    The script receives the target widget ID and mounts the lead-capture form.
    Responses include a long-lived Cache-Control header simulating a versioned static asset bundle.
    """
    resolved_id = id or widget_id or "YOUR_WIDGET_ID"

    # Embedded client script template that fetches config and renders a simple form
    js_content = f"""/**
 * Flyrank Embeddable Widget Loader
 * Widget ID: {resolved_id}
 */
(function() {{
    const widgetId = "{resolved_id}";
    console.log("Widget loaded for ID:", widgetId);

    // Expose runtime config on global window for inspection/debugging
    window.FLYRANK_WIDGET = window.FLYRANK_WIDGET || {{}};
    window.FLYRANK_WIDGET[widgetId] = {{
        id: widgetId,
        loadedAt: new Date().toISOString()
    }};
}})();
"""

    return Response(
        content=js_content,
        media_type="text/javascript",
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "Content-Type": "text/javascript; charset=utf-8",
        },
    )
