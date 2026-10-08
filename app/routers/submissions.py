"""
app/routers/submissions.py — Public form submission endpoint (Phase 2).

Pipeline (executed in this exact order for every POST):
  1. Rate limit check      — 10 req/min per IP via slowapi (→ 429 on breach)
  2. Honeypot assertion    — non-empty honeypot field → fake 200, silently dropped
  3. widget_id validation  — must be a valid UUID format (→ 404 on bad format)
  4. Widget lookup         — must exist and be active (→ 404 if not)
  5. IP extraction         — real client IP, X-Forwarded-For-aware
  6. Geo-enrichment        — two-provider fallback chain, best-effort / never crashes
  7. DB write              — INSERT submission, commit, refresh
  8. Safe side effect      — webhook/email stub, wrapped in broad try/except
  9. Return 200 success
"""

import logging
import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.submission import Submission
from app.models.widget import Widget
from app.schemas.submission import SubmissionCreate
from app.utils.geo import extract_country_code, get_geo_data
from app.utils.limiter import limiter
from app.utils.side_effects import send_webhook_or_email

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Public Submission"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, honouring reverse-proxy headers.

    Priority order:
      1. ``X-Forwarded-For`` header, leftmost entry (original client IP when
         behind a load balancer or CDN).
      2. ``X-Real-IP`` header (set by some nginx configs).
      3. ``request.client.host`` (direct connection fallback).
      4. ``"unknown"`` (last resort, prevents None from propagating).
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("X-Real-IP")
    if xri:
        return xri.strip()
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/submit/{widget_id}",
    summary="Submit a lead-capture form",
    response_description="Submission accepted",
    responses={
        200: {"description": "Submission accepted (or silently discarded as spam)"},
        404: {"description": "Widget not found or inactive"},
        422: {"description": "Validation error on request payload"},
        429: {"description": "Rate limit exceeded"},
    },
)
@router.post(
    "/api/submissions/{widget_id}",
    summary="Submit a lead-capture form (API path)",
    response_description="Submission accepted",
    include_in_schema=False,
)
@limiter.limit("10/minute")
async def submit_form(
    request: Request,              # must be first positional arg for slowapi
    widget_id: str,
    payload: SubmissionCreate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Accept a form submission from an external website visitor.

    This is the core public endpoint called by embed.js.  It is deliberately
    hardened against abuse (rate limiting, honeypot) and resilient to
    downstream failures (geo-IP, side effects).
    """

    # ------------------------------------------------------------------
    # Step 1 — Rate limit is enforced by the @limiter.limit decorator above.
    # If the limit is exceeded slowapi raises RateLimitExceeded which is
    # caught by the custom handler registered in main.py (→ 429 JSON).
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Step 2 — Honeypot check
    # Non-empty value means a bot filled in a hidden field.
    # We return a convincing 200 so the bot does not know it was detected
    # and does not change strategy or retry more aggressively.
    # ------------------------------------------------------------------
    if payload.honeypot:
        logger.info(
            "Honeypot triggered for widget_id=%s — submission silently dropped.", widget_id
        )
        return JSONResponse(content={"success": True})

    # ------------------------------------------------------------------
    # Step 3 — Validate widget_id format
    # A bad UUID format would cause an ugly DB error; fail fast with 404.
    # ------------------------------------------------------------------
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "widget_not_found"},
        )

    # ------------------------------------------------------------------
    # Step 4 — Widget lookup
    # The widget must exist AND be active.  We intentionally return the
    # same 404 for both cases (non-existence and inactive) to avoid
    # leaking information about whether a widget UUID is valid.
    # ------------------------------------------------------------------
    result = await db.execute(
        select(Widget).where(Widget.id == wid, Widget.is_active == True)  # noqa: E712
    )
    widget = result.scalar_one_or_none()
    if widget is None:
        raise HTTPException(
            status_code=404,
            detail={"success": False, "error": "widget_not_found"},
        )

    # ------------------------------------------------------------------
    # Step 5 — Extract client IP
    # ------------------------------------------------------------------
    client_ip = _get_client_ip(request)
    logger.debug("Submission from IP=%s for widget_id=%s", client_ip, widget_id)

    # ------------------------------------------------------------------
    # Step 6 — Geo-enrichment (best-effort, NEVER crashes the request)
    # The outer try/except guards against any unexpected exception from the
    # geo module itself (e.g. an import error or a bug we haven't seen yet).
    # get_geo_data() already catches its own network errors internally.
    # ------------------------------------------------------------------
    country_code: str | None = None
    try:
        geo_data = await get_geo_data(client_ip)
        country_code = extract_country_code(geo_data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Unexpected error during geo-lookup for IP=%s: %s", client_ip, exc
        )
        # country_code remains None — submission proceeds without geo tag

    # ------------------------------------------------------------------
    # Step 7 — Save to DB
    # Extract email from the submitted data as a denormalised field so
    # the tenant can filter submissions by email without parsing JSON.
    # ------------------------------------------------------------------
    raw_email = payload.data.get("email")
    submitter_email: str | None = (
        str(raw_email).strip() if isinstance(raw_email, str) and raw_email.strip() else None
    )

    submission = Submission(
        widget_id=widget.id,
        tenant_id=widget.tenant_id,
        data=payload.data,
        submitter_email=submitter_email,
        ip_address=client_ip,
        country_code=country_code,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)  # populate server-generated fields (id, submitted_at)

    logger.info(
        "Submission saved — id=%s widget=%s tenant=%s email=%s country=%s",
        submission.id,
        widget.id,
        widget.tenant_id,
        submitter_email or "(none)",
        country_code or "(unknown)",
    )

    # ------------------------------------------------------------------
    # Step 8 — Safe side effect
    # The try/except here is the single most important invariant in this
    # pipeline: even a total failure in the notification layer MUST NOT
    # change the HTTP response the visitor receives.  The submission is
    # already committed to the DB at this point.
    # ------------------------------------------------------------------
    try:
        await send_webhook_or_email(submission)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Side effect failed for submission %s (widget=%s): %s",
            submission.id, widget.id, exc,
        )

    # ------------------------------------------------------------------
    # Step 9 — Return success
    # ------------------------------------------------------------------
    return JSONResponse(content={"success": True})
