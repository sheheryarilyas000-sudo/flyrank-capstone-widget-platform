"""
app/utils/auth.py — Authentication dependencies for tenant-scoped endpoints.

Tenants authenticate using an API key passed in the X-Api-Key HTTP header.
This module verifies the key against the database and returns the active Tenant,
guaranteeing strict multi-tenant isolation.
"""

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tenant import Tenant


async def get_current_tenant(
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """FastAPI dependency to extract and authenticate the tenant.

    Accepts the API key via `X-Api-Key` header, or via `Authorization: Bearer <key>`.
    Returns the active `Tenant` model instance.
    Raises HTTP 401 if the key is missing, invalid, or belongs to an inactive tenant.
    """
    token = x_api_key
    if not token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "unauthorized", "detail": "Missing X-Api-Key header"},
            headers={"WWW-Authenticate": "ApiKey"},
        )

    stmt = select(Tenant).where(Tenant.api_key == token, Tenant.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": "unauthorized", "detail": "Invalid or inactive API key"},
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return tenant
