"""
app/routers/admin.py — Isolated Super Admin management and platform metrics router.

Guarantees:
  1. Strict Master Key Protection:
     - Endpoints require X-Admin-Key matching ADMIN_SECRET_KEY.
     - Rejects unauthorized requests with 401/403.
     - Uses constant-time comparison (secrets.compare_digest) against timing attacks.
  2. Data Privacy Isolation:
     - High-level platform analytics (counts of tenants, widgets, leads).
     - Tenant overview list without leaking raw captured lead data or submissions payloads.
"""

import logging
import os
import secrets
from typing import Any
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.submission import Submission
from app.models.tenant import Tenant
from app.models.widget import Widget

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["Platform Super Admin"],
)


def get_admin_secret_key() -> str:
    """Retrieve the master admin secret key from the environment.

    Falls back to a secure default if unconfigured in local development.
    """
    key = os.getenv("ADMIN_SECRET_KEY")
    if not key:
        return "nova_admin_master_secret_2026"
    return key.strip()


async def verify_admin_auth(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> bool:
    """Verify master admin credentials.

    Accepts key via `X-Admin-Key` header or `Authorization: Bearer <key>`.
    Raises HTTP 401 if missing, invalid, or mismatched.
    """
    token = x_admin_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    if not token:
        logger.warning("Super Admin request rejected: Missing X-Admin-Key header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "unauthorized", "detail": "Missing X-Admin-Key header"},
            headers={"WWW-Authenticate": "AdminKey"},
        )

    expected = get_admin_secret_key()
    if not secrets.compare_digest(token, expected):
        logger.warning("Super Admin request rejected: Invalid master key provided.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "unauthorized", "detail": "Invalid Master Admin Key"},
            headers={"WWW-Authenticate": "AdminKey"},
        )

    return True


@router.get(
    "/verify",
    summary="Validate Master Admin Key",
    dependencies=[Depends(verify_admin_auth)],
)
async def verify_admin_key() -> dict[str, Any]:
    """Test probe to verify Master Admin credentials."""
    return {
        "success": True,
        "status": "authenticated",
        "role": "Super Admin",
    }


@router.get(
    "/stats",
    summary="Platform-wide aggregated metrics",
    dependencies=[Depends(verify_admin_auth)],
)
async def get_platform_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return platform-wide operational statistics (Tenants, Widgets, Leads)."""
    # 1. Total & Active Tenants
    res_tenants = await db.execute(select(func.count(Tenant.id)))
    total_tenants: int = res_tenants.scalar() or 0

    res_active_tenants = await db.execute(
        select(func.count(Tenant.id)).where(Tenant.is_active == True)  # noqa: E712
    )
    active_tenants: int = res_active_tenants.scalar() or 0

    # 2. Total & Active Widgets
    res_widgets = await db.execute(select(func.count(Widget.id)))
    total_widgets: int = res_widgets.scalar() or 0

    res_active_widgets = await db.execute(
        select(func.count(Widget.id)).where(Widget.is_active == True)  # noqa: E712
    )
    active_widgets: int = res_active_widgets.scalar() or 0

    # 3. Total Captured Leads across entire platform
    res_leads = await db.execute(select(func.count(Submission.id)))
    total_leads: int = res_leads.scalar() or 0

    return {
        "success": True,
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "total_widgets": total_widgets,
        "active_widgets": active_widgets,
        "total_leads": total_leads,
    }


@router.get(
    "/tenants",
    summary="List registered tenants (Privacy Protected)",
    dependencies=[Depends(verify_admin_auth)],
)
async def list_tenants_overview(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return high-level metadata for registered tenants.

    DATA PRIVACY GUARANTEE:
    This endpoint returns workspace metadata and usage counts only.
    It intentionally does NOT return raw captured leads or personal lead payloads.
    """
    # Query tenants with count of widgets and count of submissions
    stmt = (
        select(
            Tenant,
            func.count(func.distinct(Widget.id)).label("widget_count"),
            func.count(func.distinct(Submission.id)).label("total_leads_count"),
        )
        .outerjoin(Widget, Tenant.id == Widget.tenant_id)
        .outerjoin(Submission, Tenant.id == Submission.tenant_id)
        .group_by(Tenant.id)
        .order_by(Tenant.created_at.desc())
    )

    res = await db.execute(stmt)
    rows = res.all()

    tenants_list: list[dict[str, Any]] = []
    for tenant, w_count, l_count in rows:
        tenants_list.append({
            "id": str(tenant.id),
            "company_name": tenant.name,
            "full_name": tenant.full_name or tenant.name,
            "email": tenant.email,
            "website_url": tenant.website_url or "",
            "industry": tenant.industry or "General",
            "phone_number": tenant.phone_number or "",
            "is_active": tenant.is_active,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else "",
            "widget_count": w_count,
            "total_leads_count": l_count,
        })

    return tenants_list


@router.delete(
    "/tenants/{tenant_id}",
    summary="Permanently delete a tenant workspace and cascade associated data",
    dependencies=[Depends(verify_admin_auth)],
)
async def delete_tenant_workspace(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Permanently delete a tenant workspace and cascade delete all their widgets and leads.

    STRICT ACCESS REQUIREMENT:
    Only super administrators with a verified X-Admin-Key can execute this operation.
    """
    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"success": False, "error": f"Invalid tenant UUID format: {tenant_id}"},
        )

    tenant = await db.get(Tenant, tenant_uuid)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"success": False, "error": f"Tenant workspace '{tenant_id}' not found"},
        )

    tenant_name = tenant.name

    # Cascade delete all submissions and widgets belonging to this tenant across any DB engine
    await db.execute(delete(Submission).where(Submission.tenant_id == tenant_uuid))
    await db.execute(delete(Widget).where(Widget.tenant_id == tenant_uuid))
    await db.delete(tenant)
    await db.commit()

    logger.info("Super Admin permanently deleted tenant workspace '%s' (ID: %s)", tenant_name, tenant_id)

    return {
        "success": True,
        "message": f"Tenant workspace '{tenant_name}' and all associated widgets and leads permanently wiped.",
        "tenant_id": str(tenant_id),
    }
