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
from typing import Any
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
@router.post(
    "/api/leads/{widget_id}",
    summary="Submit a lead-capture form (Leads path)",
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

    This is the core public endpoint called by embed.js. It is deliberately
    hardened against abuse (rate limiting, honeypot) and resilient to
    downstream failures (geo-IP, side effects).
    """

    # ------------------------------------------------------------------
    # Step 1 — Rate limit check (handled by decorator)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Step 2 — Honeypot check
    # ------------------------------------------------------------------
    if payload.honeypot:
        logger.info(
            "Honeypot triggered for widget_id=%s — submission silently dropped.", widget_id
        )
        return JSONResponse(content={"success": True})

    # ------------------------------------------------------------------
    # Step 3 — Validate widget_id format
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
    # ------------------------------------------------------------------
    country_code: str | None = None
    try:
        geo_data = await get_geo_data(client_ip)
        country_code = extract_country_code(geo_data)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Unexpected error during geo-lookup for IP=%s: %s", client_ip, exc
        )

    # ------------------------------------------------------------------
    # Step 7 — Merge payload & extract extended B2B fields
    # ------------------------------------------------------------------
    form_data = dict(payload.data) if payload.data else {}
    if hasattr(payload, "model_extra") and payload.model_extra:
        for k, v in payload.model_extra.items():
            if k not in ("honeypot", "widget_id") and k not in form_data:
                form_data[k] = v

    # Extract email
    raw_email = form_data.get("email") or form_data.get("work_email") or form_data.get("contact_email")
    submitter_email: str | None = (
        str(raw_email).strip() if isinstance(raw_email, str) and raw_email.strip() else None
    )

    # Extract phone
    raw_phone = form_data.get("phone") or form_data.get("phone_number") or form_data.get("tel") or form_data.get("telephone")
    phone: str | None = (
        str(raw_phone).strip() if isinstance(raw_phone, str) and raw_phone.strip() else None
    )

    # Extract company
    raw_company = form_data.get("lead_company") or form_data.get("company") or form_data.get("company_name") or form_data.get("organization")
    lead_company: str | None = (
        str(raw_company).strip() if isinstance(raw_company, str) and raw_company.strip() else None
    )

    submission = Submission(
        widget_id=widget.id,
        tenant_id=widget.tenant_id,
        data=form_data,
        submitter_email=submitter_email,
        phone=phone,
        lead_company=lead_company,
        ip_address=client_ip,
        country_code=country_code,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    logger.info(
        "Submission saved — id=%s widget=%s tenant=%s email=%s phone=%s company=%s country=%s",
        submission.id,
        widget.id,
        widget.tenant_id,
        submitter_email or "(none)",
        phone or "(none)",
        lead_company or "(none)",
        country_code or "(unknown)",
    )

    # ------------------------------------------------------------------
    # Step 8 — Safe side effect
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
    return JSONResponse(content={"success": True, "id": str(submission.id), "data": form_data})


@router.post(
    "/api/leads",
    summary="Direct lead capture endpoint",
    response_description="Lead submission accepted",
    responses={
        200: {"description": "Lead accepted and enriched"},
        400: {"description": "Missing widget identification"},
        404: {"description": "Widget not found or inactive"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit("20/minute")
async def capture_lead_direct(
    request: Request,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Accept lead data directly from custom HTML forms or B2B integrations.

    Accepts arbitrary JSON payloads (name, email, phone, lead_company, budget, message, etc.)
    either nested under `data` or as a flat JSON dictionary.
    """
    # 1. Honeypot trap
    honeypot = payload.get("honeypot") or (
        payload.get("data", {}).get("honeypot") if isinstance(payload.get("data"), dict) else ""
    )
    if honeypot:
        logger.info("Direct lead honeypot triggered — silently dropped.")
        return JSONResponse(content={"success": True})

    # 2. Extract or resolve widget_id
    raw_wid = (
        payload.get("widget_id")
        or request.query_params.get("widget_id")
        or (payload.get("data", {}).get("widget_id") if isinstance(payload.get("data"), dict) else None)
    )

    widget: Widget | None = None
    if raw_wid:
        try:
            wid = uuid_lib.UUID(str(raw_wid))
            result = await db.execute(
                select(Widget).where(Widget.id == wid, Widget.is_active == True)  # noqa: E712
            )
            widget = result.scalar_one_or_none()
        except ValueError:
            raise HTTPException(status_code=400, detail={"success": False, "error": "invalid_widget_id"})
    else:
        # Fallback to the most recent active widget
        result = await db.execute(
            select(Widget).where(Widget.is_active == True).order_by(Widget.created_at.desc()).limit(1)  # noqa: E712
        )
        widget = result.scalar_one_or_none()

    if widget is None:
        raise HTTPException(status_code=404, detail={"success": False, "error": "active_widget_required"})

    # 3. Format form data
    raw_data = payload.get("data")
    if isinstance(raw_data, dict):
        form_data = dict(raw_data)
        for k, v in payload.items():
            if k not in ("data", "honeypot", "widget_id") and k not in form_data:
                form_data[k] = v
    else:
        form_data = {k: v for k, v in payload.items() if k not in ("honeypot", "widget_id")}

    # 4. Extract standard fields
    raw_email = form_data.get("email") or form_data.get("work_email") or form_data.get("contact_email")
    submitter_email = str(raw_email).strip() if isinstance(raw_email, str) and raw_email.strip() else None

    raw_phone = form_data.get("phone") or form_data.get("phone_number") or form_data.get("tel") or form_data.get("telephone")
    phone = str(raw_phone).strip() if isinstance(raw_phone, str) and raw_phone.strip() else None

    raw_company = form_data.get("lead_company") or form_data.get("company") or form_data.get("company_name") or form_data.get("organization")
    lead_company = str(raw_company).strip() if isinstance(raw_company, str) and raw_company.strip() else None

    # 5. Geo-enrichment
    client_ip = _get_client_ip(request)
    country_code: str | None = None
    try:
        geo_data = await get_geo_data(client_ip)
        country_code = extract_country_code(geo_data)
    except Exception:
        pass

    # 6. Save Submission
    submission = Submission(
        widget_id=widget.id,
        tenant_id=widget.tenant_id,
        data=form_data,
        submitter_email=submitter_email,
        phone=phone,
        lead_company=lead_company,
        ip_address=client_ip,
        country_code=country_code,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    # 7. Side effects
    try:
        await send_webhook_or_email(submission)
    except Exception:
        pass

    return JSONResponse(
        content={
            "success": True,
            "lead_id": str(submission.id),
            "widget_id": str(widget.id),
            "data": form_data,
        }
    )
