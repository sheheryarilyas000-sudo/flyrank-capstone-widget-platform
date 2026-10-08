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
from app.utils.auth import get_current_tenant

router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard & Analytics"],
)


@router.get(
    "/stats",
    summary="Get tenant analytics and submission metrics",
    response_description="Total submission count and geo-location breakdown",
)
async def get_dashboard_stats(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve submission statistics for the authenticated tenant.

    Guarantees:
      - Complete tenant isolation: only submissions belonging to `tenant.id` are aggregated.
      - Returns the total count of submissions across all widgets owned by this tenant.
      - Returns a grouped breakdown by country code (geo-location stats).
    """
    # 1. Total submissions count for authenticated tenant
    total_stmt = (
        select(func.count(Submission.id))
        .where(Submission.tenant_id == tenant.id)
    )
    total_result = await db.execute(total_stmt)
    total_submissions: int = total_result.scalar() or 0

    # 2. Grouped breakdown by country code
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

    return {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "total_submissions": total_submissions,
        "by_country": by_country,
        "country_breakdown": country_breakdown,
    }
