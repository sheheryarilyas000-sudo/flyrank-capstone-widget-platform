"""
app/routers/auth.py — Public self-serve tenant onboarding & Hybrid OTP API Key Recovery.

Provides:
  POST /api/register (and alias /api/v1/auth/register):
    Allows new users to create a workspace (Tenant) with their Name, Company,
    and Work Email. Generates a secure nova_live_... API key and auto-provisions
    their first starter embeddable widget.

  POST /api/auth/recover/request (and alias /api/v1/auth/recover/request):
    Generates a secure 6-digit numeric OTP with 5-minute expiry.
    Smart Fallback:
      - If RESEND_API_KEY is present in env, delivers via Resend API.
      - If NOT present (local dev mode), prints clearly to terminal console for instant testing.

  POST /api/auth/recover/verify (and alias /api/v1/auth/recover/verify):
    Validates the 6-digit OTP, regenerates the live API key, and returns the new key.
"""

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tenant import Tenant
from app.models.widget import Widget

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Authentication & Onboarding"],
)

# ---------------------------------------------------------------------------
# In-Memory Recovery Store
# email -> { "otp": "123456", "expires_at": datetime, "tenant_id": uuid, "attempts": 0 }
# ---------------------------------------------------------------------------
_recovery_store: dict[str, dict[str, Any]] = {}


def is_production_mode() -> bool:
    env = os.environ.get("APP_ENV", "").lower()
    return env == "production" or os.environ.get("VERCEL", "") == "1"


def print_otp_to_console(email: str, otp: str, expires_at: datetime) -> None:
    """Print high-visibility OTP banner to terminal when running in development mode without Resend API key."""
    if is_production_mode():
        # Never print sensitive OTP credentials to stdout in production
        return

    banner = f"""
======================================================================
[NOVA LEADS LOCAL RECOVERY OTP]
Destination Email: {email}
One-Time Password (OTP): {otp}
Validity: 5 Minutes (Expires: {expires_at.strftime('%H:%M:%S UTC')})
(Development Mode Fallback: RESEND_API_KEY not configured.)
======================================================================
"""
    try:
        print(banner, flush=True)
    except Exception:
        import sys
        sys.stdout.buffer.write(banner.encode("utf-8", errors="replace"))
        sys.stdout.flush()


async def send_otp_hybrid(email: str, company: str, otp: str, expires_at: datetime) -> bool:
    """Send OTP via Resend if RESEND_API_KEY is available, or fallback to console print in development.

    In production: strictly requires Resend email delivery and raises an error on failure
    rather than leaking sensitive OTPs to logs.
    """
    resend_api_key = os.environ.get("RESEND_API_KEY")
    is_prod = is_production_mode()

    if resend_api_key:
        try:
            import resend  # type: ignore

            resend.api_key = resend_api_key
            sender = os.environ.get(
                "RESEND_FROM_EMAIL", "Nova Leads Security <onboarding@resend.dev>"
            )

            html_body = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 540px; margin: 0 auto; padding: 32px 24px; border: 1px solid #e2e8f0; border-radius: 16px; background-color: #ffffff;">
                <div style="margin-bottom: 24px; text-align: center;">
                    <h2 style="color: #4f46e5; margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">Nova Leads</h2>
                    <p style="color: #64748b; font-size: 13px; margin: 4px 0 0 0;">Workspace Security & Authentication</p>
                </div>
                <h3 style="color: #0f172a; margin-top: 0; font-size: 18px;">API Key Recovery Code</h3>
                <p style="color: #475569; font-size: 14px; line-height: 1.6;">
                    We received a request to recover the API key for your workspace <strong>{company}</strong> ({email}).
                </p>
                <div style="background: linear-gradient(135deg, #eef2ff 0%, #f1f5f9 100%); border: 1px solid #cbd5e1; border-radius: 12px; padding: 20px; text-align: center; margin: 24px 0;">
                    <span style="font-family: monospace; font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #4338ca;">{otp}</span>
                </div>
                <p style="color: #64748b; font-size: 13px; line-height: 1.5;">
                    This verification code is strictly valid for <strong>5 minutes</strong>. If you did not initiate this request, you can safely disregard this email.
                </p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
                <p style="color: #94a3b8; font-size: 11px; text-align: center; margin: 0;">
                    Nova Leads Embeddable Lead-Capture Platform &copy; 2026. All rights reserved.
                </p>
            </div>
            """

            resend.Emails.send({
                "from": sender,
                "to": [email],
                "subject": f"Nova Leads: {otp} is your API key recovery code",
                "html": html_body,
            })
            logger.info("Successfully dispatched recovery OTP email to %s via Resend.", email)
            return True
        except Exception as exc:
            logger.error("Resend email delivery failed: %s", exc)
            if is_prod:
                raise HTTPException(
                    status_code=502,
                    detail="Failed to deliver recovery verification email. Please verify your email configuration or contact support."
                )
            print_otp_to_console(email, otp, expires_at)
            return False
    else:
        if is_prod:
            logger.error("RESEND_API_KEY is not set in production. Refusing to log OTP to stdout.")
            raise HTTPException(
                status_code=503,
                detail="Email delivery service is unconfigured. Please configure RESEND_API_KEY in production."
            )
        print_otp_to_console(email, otp, expires_at)
        return False


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    """Payload for self-serve workspace onboarding."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="User's full name",
        example="Sarah Connor",
    )
    company: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Company or organization workspace name",
        example="Resistance AI",
    )
    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="User's work email address",
        example="sarah@resistance.ai",
    )


class RecoverRequestPayload(BaseModel):
    """Payload to request an OTP code for API key recovery."""

    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="User's registered workspace email",
        example="sarah@resistance.ai",
    )


class RecoverVerifyPayload(BaseModel):
    """Payload to verify an OTP and regenerate the live API key."""

    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        description="User's registered workspace email",
        example="sarah@resistance.ai",
    )
    otp: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="6-digit verification code",
        example="123456",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post(
    "/api/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new workspace tenant",
    response_description="New tenant credentials and provisioned starter widget ID",
)
@router.post(
    "/api/v1/auth/register",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def register_tenant(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a new Tenant workspace and generate an API key."""
    cleaned_name = payload.name.strip()
    cleaned_company = payload.company.strip()
    cleaned_email = payload.email.strip().lower()

    # Basic RFC-compliant email pattern check
    email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(email_regex, cleaned_email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "success": False,
                "error": "invalid_email_format",
                "detail": "Please provide a valid email address.",
            },
        )

    # Check if a tenant with this email already exists
    stmt = select(Tenant).where(Tenant.email == cleaned_email)
    res = await db.execute(stmt)
    existing_tenant = res.scalar_one_or_none()

    if existing_tenant is not None and existing_tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "success": False,
                "error": "email_already_registered",
                "detail": (
                    f"An account for '{cleaned_email}' already exists. "
                    "Please log in using your Tenant API key or use 'Forgot API Key'."
                ),
            },
        )

    # Generate secure live API key
    api_key = f"nova_live_{secrets.token_hex(16)}"

    # Create new Tenant record
    new_tenant = Tenant(
        name=cleaned_company,
        full_name=cleaned_name,
        email=cleaned_email,
        api_key=api_key,
        is_active=True,
    )
    db.add(new_tenant)
    await db.flush()  # Flush to generate new_tenant.id

    # Auto-provision starter widget
    starter_widget = Widget(
        tenant_id=new_tenant.id,
        name=f"{cleaned_company} Lead Capture Form",
        config={
            "title": f"Connect with {cleaned_company}",
            "subtitle": "Sign up today to receive 20% off your first 3 months",
            "offer_text": "Sign up today to receive 20% off your first 3 months",
            "submit_label": "Claim Offer & Join",
            "success_message": "Thanks! Check your email for confirmation.",
            "fields": [
                {
                    "name": "full_name",
                    "type": "text",
                    "label": "Full Name",
                    "required": True,
                    "placeholder": cleaned_name,
                },
                {
                    "name": "email",
                    "type": "email",
                    "label": "Work Email",
                    "required": True,
                    "placeholder": cleaned_email,
                },
                {
                    "name": "phone",
                    "type": "tel",
                    "label": "Phone Number",
                    "required": False,
                    "placeholder": "+1 (555) 000-0000",
                },
                {
                    "name": "company",
                    "type": "text",
                    "label": "Company Name",
                    "required": False,
                    "placeholder": cleaned_company,
                },
                {
                    "name": "service",
                    "type": "select",
                    "label": "Required Service",
                    "required": False,
                    "options": [
                        "Enterprise SaaS",
                        "Growth Consulting",
                        "Custom Integration",
                    ],
                },
                {
                    "name": "message",
                    "type": "textarea",
                    "label": "Project Details",
                    "required": False,
                    "placeholder": "Tell us about your requirements...",
                },
            ],
        },
        allowed_origins=["*"],
        is_active=True,
    )
    db.add(starter_widget)
    await db.commit()
    await db.refresh(new_tenant)
    await db.refresh(starter_widget)

    logger.info(
        "Registered new tenant: id=%s, company=%s, email=%s, starter_widget=%s",
        new_tenant.id,
        new_tenant.name,
        new_tenant.email,
        starter_widget.id,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "success": True,
            "tenant_id": str(new_tenant.id),
            "name": new_tenant.name,
            "full_name": new_tenant.full_name or new_tenant.name,
            "email": new_tenant.email,
            "api_key": new_tenant.api_key,
            "starter_widget_id": str(starter_widget.id),
            "message": f"Workspace '{new_tenant.name}' registered successfully.",
        },
    )


@router.post(
    "/api/auth/recover/request",
    summary="Request a 6-digit OTP code to recover API key",
    response_description="Confirmation of OTP generation and dispatch method",
)
@router.post(
    "/api/v1/auth/recover/request",
    include_in_schema=False,
)
async def request_recovery_otp(
    payload: RecoverRequestPayload,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate a secure 6-digit OTP for API Key recovery with 5-minute expiry.

    Smart Fallback:
      - Uses Resend when RESEND_API_KEY environment variable is present.
      - Uses console terminal output in local developer environment.
    """
    cleaned_email = payload.email.strip().lower()

    stmt = select(Tenant).where(Tenant.email == cleaned_email, Tenant.is_active == True)  # noqa: E712
    res = await db.execute(stmt)
    tenant = res.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": "tenant_not_found",
                "detail": f"No active workspace found for '{cleaned_email}'. Please register first.",
            },
        )

    # Generate secure 6-digit numeric OTP
    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    _recovery_store[cleaned_email] = {
        "otp": otp,
        "expires_at": expires_at,
        "tenant_id": tenant.id,
        "attempts": 0,
    }

    # Dispatch via hybrid sender (Resend or Console print)
    delivered_via_resend = await send_otp_hybrid(cleaned_email, tenant.name, otp, expires_at)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": (
                "A 6-digit recovery code has been sent to your email."
                if delivered_via_resend
                else "Recovery code generated! (Local dev mode: OTP printed to server terminal)"
            ),
            "email": cleaned_email,
            "dev_mode": not delivered_via_resend,
            "expires_in_seconds": 300,
        },
    )


@router.post(
    "/api/auth/recover/verify",
    summary="Verify recovery OTP and regenerate live API key",
    response_description="Validated tenant credentials with new API key",
)
@router.post(
    "/api/v1/auth/recover/verify",
    include_in_schema=False,
)
async def verify_recovery_otp(
    payload: RecoverVerifyPayload,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Verify 6-digit OTP, regenerate the API key, and return the new token."""
    cleaned_email = payload.email.strip().lower()
    cleaned_otp = payload.otp.strip()

    if cleaned_email not in _recovery_store:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "no_pending_request",
                "detail": "No pending recovery code requested for this email. Please request a new code.",
            },
        )

    entry = _recovery_store[cleaned_email]
    now = datetime.now(timezone.utc)

    # Check expiration
    if now > entry["expires_at"]:
        _recovery_store.pop(cleaned_email, None)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "code_expired",
                "detail": "Recovery code has expired (5-minute limit). Please request a fresh code.",
            },
        )

    # Check rate limit on attempts
    if entry.get("attempts", 0) >= 5:
        _recovery_store.pop(cleaned_email, None)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "success": False,
                "error": "too_many_attempts",
                "detail": "Too many failed attempts. Please request a new recovery code.",
            },
        )

    # Check OTP match
    if entry["otp"] != cleaned_otp:
        entry["attempts"] = entry.get("attempts", 0) + 1
        remaining = 5 - entry["attempts"]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "invalid_code",
                "detail": f"Invalid 6-digit code. {remaining} attempt(s) remaining.",
            },
        )

    # Code matches! Retrieve tenant and regenerate API key
    stmt = select(Tenant).where(Tenant.email == cleaned_email, Tenant.is_active == True)  # noqa: E712
    res = await db.execute(stmt)
    tenant = res.scalar_one_or_none()

    if tenant is None:
        _recovery_store.pop(cleaned_email, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": "tenant_not_found",
                "detail": "Workspace account not found.",
            },
        )

    new_api_key = f"nova_live_{secrets.token_hex(16)}"
    tenant.api_key = new_api_key
    await db.commit()
    await db.refresh(tenant)

    # Clear recovery session
    _recovery_store.pop(cleaned_email, None)

    logger.info("Successfully verified OTP and rotated API key for tenant: %s", tenant.email)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": "Recovery code verified! New API key generated successfully.",
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "full_name": tenant.full_name or tenant.name,
            "email": tenant.email,
            "api_key": new_api_key,
        },
    )
