"""
app/routers/tenant.py — Authenticated tenant profile management & lifecycle endpoints.

Provides:
  - GET  /api/tenant/profile: View authenticated tenant profile details.
  - PUT  /api/tenant/profile: Update user Full Name, Company Name, and Contact Email.
  - POST /api/tenant/regenerate-key: Rotate the live API key from authenticated settings.
  - DELETE /api/tenant: Permanently cascade-delete workspace, widgets, and submissions.
"""

import logging
import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.submission import Submission
from app.models.tenant import Tenant
from app.models.widget import Widget
from app.utils.auth import get_current_tenant

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/tenant",
    tags=["Tenant Profile & Settings"],
)


class UpdateProfileRequest(BaseModel):
    """Payload for updating user profile settings."""

    name: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="User's full name",
        example="Sarah Connor",
    )
    company: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Company / Workspace name",
        example="Resistance AI",
    )
    email: str | None = Field(
        None,
        min_length=5,
        max_length=255,
        description="Contact work email",
        example="sarah@resistance.ai",
    )
    website_url: str | None = Field(
        None,
        max_length=500,
        description="Company website URL",
        example="https://resistance.ai",
    )
    industry: str | None = Field(
        None,
        max_length=100,
        description="Business industry or sector",
        example="Tech",
    )
    phone_number: str | None = Field(
        None,
        max_length=50,
        description="Business contact phone number",
        example="+1 (555) 019-2834",
    )


@router.get(
    "/profile",
    summary="Get authenticated tenant profile",
    response_description="Profile details for current workspace",
)
async def get_profile(
    tenant: Tenant = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Retrieve profile and workspace details for the authenticated tenant."""
    return {
        "success": True,
        "tenant_id": str(tenant.id),
        "name": tenant.full_name or tenant.name,
        "full_name": tenant.full_name or tenant.name,
        "company": tenant.name,
        "email": tenant.email,
        "website_url": tenant.website_url or "",
        "industry": tenant.industry or "",
        "phone_number": tenant.phone_number or "",
        "api_key": tenant.api_key,
        "is_active": tenant.is_active,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
    }


@router.put(
    "/profile",
    summary="Update authenticated tenant profile",
    response_description="Updated tenant profile details",
)
async def update_profile(
    payload: UpdateProfileRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update profile attributes (Name, Company, Email, Website, Industry, Phone) for the workspace."""
    updated = False

    # 1. Update Full Name
    if payload.name is not None:
        cleaned_name = payload.name.strip()
        if cleaned_name:
            tenant.full_name = cleaned_name
            updated = True

    # 2. Update Company Name
    if payload.company is not None:
        cleaned_company = payload.company.strip()
        if cleaned_company:
            tenant.name = cleaned_company
            updated = True

    # 3. Update Email
    if payload.email is not None:
        cleaned_email = payload.email.strip().lower()
        if cleaned_email and cleaned_email != (tenant.email or "").lower():
            # Validate format
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

            # Check duplicate email
            dup_stmt = select(Tenant).where(
                Tenant.email == cleaned_email,
                Tenant.id != tenant.id,
                Tenant.is_active == True,  # noqa: E712
            )
            dup_res = await db.execute(dup_stmt)
            if dup_res.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "success": False,
                        "error": "email_already_in_use",
                        "detail": f"The email '{cleaned_email}' is already registered to another workspace.",
                    },
                )
            tenant.email = cleaned_email
            updated = True

    # 4. Update Website URL
    if payload.website_url is not None:
        tenant.website_url = payload.website_url.strip() or None
        updated = True

    # 5. Update Industry
    if payload.industry is not None:
        tenant.industry = payload.industry.strip() or None
        updated = True

    # 6. Update Phone Number
    if payload.phone_number is not None:
        tenant.phone_number = payload.phone_number.strip() or None
        updated = True

    if updated:
        await db.commit()
        await db.refresh(tenant)
        logger.info("Updated tenant profile: id=%s, company=%s", tenant.id, tenant.name)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": "Profile updated successfully.",
            "tenant_id": str(tenant.id),
            "name": tenant.full_name or tenant.name,
            "full_name": tenant.full_name or tenant.name,
            "company": tenant.name,
            "email": tenant.email,
            "website_url": tenant.website_url or "",
            "industry": tenant.industry or "",
            "phone_number": tenant.phone_number or "",
            "api_key": tenant.api_key,
        },
    )


@router.post(
    "/regenerate-key",
    summary="Regenerate live API key",
    response_description="Newly rotated API key",
)
async def regenerate_api_key(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate a new secure API key, invalidating the previous token."""
    new_api_key = f"nova_live_{secrets.token_hex(16)}"
    tenant.api_key = new_api_key
    await db.commit()
    await db.refresh(tenant)

    logger.warning("Regenerated API key for tenant: id=%s", tenant.id)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": "API key successfully regenerated.",
            "api_key": new_api_key,
        },
    )


@router.delete(
    "",
    summary="Cascade delete tenant workspace",
    response_description="Confirmation of permanent workspace deletion",
)
async def delete_tenant(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Permanently delete workspace, all widgets, and all submissions (cascade delete)."""
    tenant_id = tenant.id
    tenant_name = tenant.name

    # Explicit cascade delete for multi-engine compatibility
    await db.execute(delete(Submission).where(Submission.tenant_id == tenant_id))
    await db.execute(delete(Widget).where(Widget.tenant_id == tenant_id))
    await db.delete(tenant)
    await db.commit()

    logger.warning(
        "Permanently deleted tenant workspace: id=%s, name=%s", tenant_id, tenant_name
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "message": f"Workspace '{tenant_name}' and all associated data permanently deleted.",
        },
    )
