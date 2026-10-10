"""
app/routers/dashboard.py — Owner Dashboard and Analytics API.

Provides authenticated metrics and submission statistics.
Multi-tenant isolation is strictly enforced: every query is scoped by `tenant_id`
resolved from the caller's authenticated Tenant model.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.submission import Submission
from app.models.tenant import Tenant
from app.models.widget import Widget
from app.utils.auth import get_current_tenant

router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard & Analytics"],
)


@router.get(
    "/stats",
    summary="Get tenant analytics and submission metrics",
    response_description="Total submission count, widgets count, and geo-location breakdown",
)
async def get_dashboard_stats(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve submission statistics for the authenticated tenant.

    Guarantees:
      - Complete tenant isolation: only submissions belonging to `tenant.id` are aggregated.
      - Returns the total count of submissions across all widgets owned by this tenant.
      - Returns the total count of active widgets owned by this tenant.
      - Returns a grouped breakdown by country code (geo-location stats).
      - Returns recent activity items for the dashboard overview.
    """
    # 1. Total submissions count for authenticated tenant
    total_stmt = (
        select(func.count(Submission.id))
        .where(Submission.tenant_id == tenant.id)
    )
    total_result = await db.execute(total_stmt)
    total_submissions: int = total_result.scalar() or 0

    # 2. Total active widgets count
    widget_stmt = (
        select(func.count(Widget.id))
        .where(Widget.tenant_id == tenant.id, Widget.is_active == True)
    )
    widget_result = await db.execute(widget_stmt)
    total_widgets: int = widget_result.scalar() or 0

    # 3. Grouped breakdown by country code
    geo_stmt = (
        select(
            Submission.country_code,
            func.count(Submission.id).label("count"),
        )
        .where(Submission.tenant_id == tenant.id)
        .group_by(Submission.country_code)
        .order_by(func.count(Submission.id).desc())
    )
    geo_result = await db.execute(geo_stmt)
    geo_rows = geo_result.all()

    # Build mapping and breakdown list
    by_country: dict[str, int] = {}
    country_breakdown: list[dict[str, Any]] = []

    for code, count in geo_rows:
        country_name = code if code else "Unknown"
        by_country[country_name] = count
        country_breakdown.append({
            "country": country_name,
            "count": count,
        })

    # 4. Recent activity (last 5 submissions)
    recent_stmt = (
        select(Submission, Widget.name.label("widget_name"))
        .outerjoin(Widget, Submission.widget_id == Widget.id)
        .where(Submission.tenant_id == tenant.id)
        .order_by(Submission.submitted_at.desc())
        .limit(5)
    )
    recent_res = await db.execute(recent_stmt)
    recent_rows = recent_res.all()

    recent_activity = [
        {
            "id": str(sub.id),
            "email": sub.submitter_email or "Anonymous",
            "name": sub.data.get("full_name") or sub.data.get("name") or "",
            "widget_name": w_name or "Unknown Form",
            "country": sub.country_code or "Unknown",
            "timestamp": sub.submitted_at.isoformat() if sub.submitted_at else "",
        }
        for sub, w_name in recent_rows
    ]

    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "total_widgets": total_widgets,
        "total_submissions": total_submissions,
        "by_country": by_country,
        "country_breakdown": country_breakdown,
        "recent_activity": recent_activity,
    }
