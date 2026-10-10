"""
app/routers/widgets.py — Widget management routes (private, tenant-authenticated).

All routes here require a valid X-Api-Key or Authorization Bearer header that resolves to an active
Tenant. Every ORM query is scoped by tenant_id — a tenant can never read
or mutate another tenant's widgets or submissions.
"""

from typing import Any
import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.submission import Submission
from app.models.tenant import Tenant
from app.models.widget import Widget
from app.schemas.widget import WidgetCreate, WidgetUpdate
from app.utils.auth import get_current_tenant

router = APIRouter(
    tags=["Widget Management"],
)


@router.post("/api/widgets", status_code=status.HTTP_201_CREATED, include_in_schema=False)
@router.post("/api/v1/widgets", status_code=status.HTTP_201_CREATED)
async def create_widget(
    payload: WidgetCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new embeddable widget for the authenticated tenant."""
    widget = Widget(
        tenant_id=tenant.id,
        name=payload.name,
        config=payload.config,
        allowed_origins=payload.allowed_origins,
        is_active=True,
    )
    db.add(widget)
    await db.commit()
    await db.refresh(widget)

    return {
        "id": str(widget.id),
        "tenant_id": str(widget.tenant_id),
        "name": widget.name,
        "config": widget.config,
        "allowed_origins": widget.allowed_origins,
        "is_active": widget.is_active,
        "created_at": widget.created_at.isoformat() if widget.created_at else "",
        "updated_at": widget.updated_at.isoformat() if widget.updated_at else "",
    }


@router.get("/api/widgets", include_in_schema=False)
@router.get("/api/v1/widgets")
async def list_widgets(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all widgets owned by the authenticated tenant."""
    stmt = (
        select(Widget)
        .where(Widget.tenant_id == tenant.id, Widget.is_active == True)
        .order_by(Widget.created_at.desc())
    )
    result = await db.execute(stmt)
    widgets = result.scalars().all()

    return [
        {
            "id": str(w.id),
            "tenant_id": str(w.tenant_id),
            "name": w.name,
            "config": w.config,
            "allowed_origins": w.allowed_origins,
            "is_active": w.is_active,
            "created_at": w.created_at.isoformat() if w.created_at else "",
            "updated_at": w.updated_at.isoformat() if w.updated_at else "",
        }
        for w in widgets
    ]


@router.get("/api/widgets/{widget_id}", include_in_schema=False)
@router.get("/api/v1/widgets/{widget_id}")
async def get_widget(
    widget_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve a single widget by ID."""
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Widget not found")

    stmt = select(Widget).where(
        Widget.id == wid,
        Widget.tenant_id == tenant.id,
        Widget.is_active == True,
    )
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()

    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found")

    return {
        "id": str(widget.id),
        "tenant_id": str(widget.tenant_id),
        "name": widget.name,
        "config": widget.config,
        "allowed_origins": widget.allowed_origins,
        "is_active": widget.is_active,
        "created_at": widget.created_at.isoformat() if widget.created_at else "",
        "updated_at": widget.updated_at.isoformat() if widget.updated_at else "",
    }


@router.put("/api/widgets/{widget_id}")
@router.patch("/api/widgets/{widget_id}", include_in_schema=False)
@router.put("/api/v1/widgets/{widget_id}", include_in_schema=False)
@router.patch("/api/v1/widgets/{widget_id}")
async def update_widget(
    widget_id: str,
    payload: WidgetUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Partially update a widget's name, config, or allowed_origins."""
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Widget not found")

    stmt = select(Widget).where(
        Widget.id == wid,
        Widget.tenant_id == tenant.id,
    )
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()

    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found")

    if payload.name is not None:
        widget.name = payload.name
    if payload.config is not None:
        widget.config = payload.config
    if payload.allowed_origins is not None:
        widget.allowed_origins = payload.allowed_origins
    if payload.is_active is not None:
        widget.is_active = payload.is_active

    await db.commit()
    await db.refresh(widget)

    return {
        "id": str(widget.id),
        "tenant_id": str(widget.tenant_id),
        "name": widget.name,
        "config": widget.config,
        "allowed_origins": widget.allowed_origins,
        "is_active": widget.is_active,
        "created_at": widget.created_at.isoformat() if widget.created_at else "",
        "updated_at": widget.updated_at.isoformat() if widget.updated_at else "",
    }


@router.delete("/api/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
@router.delete("/api/v1/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget(
    widget_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a widget (sets is_active=False)."""
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Widget not found")

    stmt = select(Widget).where(
        Widget.id == wid,
        Widget.tenant_id == tenant.id,
    )
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()

    if not widget:
        raise HTTPException(status_code=404, detail="Widget not found")

    widget.is_active = False
    await db.commit()


@router.get("/api/widgets/{widget_id}/submissions", include_in_schema=False)
@router.get("/api/v1/widgets/{widget_id}/submissions")
async def list_widget_submissions(
    widget_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all submissions for a specific widget."""
    try:
        wid = uuid_lib.UUID(widget_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Widget not found")

    stmt = (
        select(Submission)
        .where(Submission.widget_id == wid, Submission.tenant_id == tenant.id)
        .order_by(Submission.submitted_at.desc())
    )
    result = await db.execute(stmt)
    submissions = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "widget_id": str(s.widget_id),
            "tenant_id": str(s.tenant_id),
            "submitter_email": s.submitter_email or "",
            "phone": s.phone or s.data.get("phone") or "",
            "lead_company": s.lead_company or s.data.get("lead_company") or s.data.get("company") or "",
            "name": s.data.get("full_name") or s.data.get("name") or "",
            "data": s.data,
            "ip_address": s.ip_address or "",
            "country_code": s.country_code or "Unknown",
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else "",
        }
        for s in submissions
    ]


@router.get("/api/submissions", include_in_schema=False)
@router.get("/api/v1/submissions")
async def list_all_submissions(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all submissions across all widgets owned by the authenticated tenant."""
    # Also fetch widget names to display in the table
    stmt = (
        select(Submission, Widget.name.label("widget_name"))
        .outerjoin(Widget, Submission.widget_id == Widget.id)
        .where(Submission.tenant_id == tenant.id)
        .order_by(Submission.submitted_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(sub.id),
            "widget_id": str(sub.widget_id),
            "widget_name": widget_name or "Unknown Form",
            "tenant_id": str(sub.tenant_id),
            "submitter_email": sub.submitter_email or "",
            "phone": sub.phone or sub.data.get("phone") or "",
            "lead_company": sub.lead_company or sub.data.get("lead_company") or sub.data.get("company") or "",
            "name": sub.data.get("full_name") or sub.data.get("name") or "",
            "data": sub.data,
            "ip_address": sub.ip_address or "",
            "country_code": sub.country_code or "Unknown",
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else "",
        }
        for sub, widget_name in rows
    ]
