"""
app/routers/widgets.py — Widget management routes (private, tenant-authenticated).

All routes here require a valid X-Api-Key header that resolves to an active
Tenant.  Every ORM query is scoped by tenant_id — a tenant can never read
or mutate another tenant's widgets.

Phase 2 will implement the full business logic; this file defines the router
skeleton with route signatures and docstrings ready for implementation.
"""

from fastapi import APIRouter

router = APIRouter(
    prefix="/api/v1/widgets",
    tags=["Widget Management"],
)


@router.post("", status_code=201)
async def create_widget():
    """Create a new embeddable widget for the authenticated tenant.

    Requires: X-Api-Key header
    Body: WidgetCreate schema (name, config, allowed_origins)
    Returns: WidgetRead schema (201 Created)
    """
    # TODO (Phase 2): resolve tenant from X-Api-Key dependency
    # TODO (Phase 2): validate body against WidgetCreate Pydantic schema
    # TODO (Phase 2): INSERT widget with tenant_id = authed_tenant.id
    raise NotImplementedError("Phase 2")


@router.get("")
async def list_widgets():
    """List all widgets owned by the authenticated tenant.

    Returns: list[WidgetRead]
    Multi-tenant isolation: WHERE tenant_id = authed_tenant.id
    """
    raise NotImplementedError("Phase 2")


@router.get("/{widget_id}")
async def get_widget(widget_id: str):
    """Retrieve a single widget by ID.

    Returns 404 if the widget does not exist OR belongs to a different tenant.
    """
    raise NotImplementedError("Phase 2")


@router.patch("/{widget_id}")
async def update_widget(widget_id: str):
    """Partially update a widget's name, config, or allowed_origins.

    Only the authenticated tenant's widgets are reachable.
    Returns: WidgetRead
    """
    raise NotImplementedError("Phase 2")


@router.delete("/{widget_id}", status_code=204)
async def delete_widget(widget_id: str):
    """Soft-delete a widget (sets is_active=False).

    Hard delete is intentionally avoided so historical submissions remain
    traceable to their originating widget.
    """
    raise NotImplementedError("Phase 2")


# ---------------------------------------------------------------------------
# Submission sub-resource (tenant-scoped)
# ---------------------------------------------------------------------------

@router.get("/{widget_id}/submissions")
async def list_submissions(widget_id: str):
    """List all submissions for a specific widget.

    Tenant isolation: widget must belong to authed tenant; submissions
    filtered by both widget_id AND tenant_id.
    Returns: list[SubmissionRead]
    """
    raise NotImplementedError("Phase 2")
