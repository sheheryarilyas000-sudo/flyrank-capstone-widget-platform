"""
app/models/tenant.py — Tenant ORM model.

A Tenant represents a paying customer of the platform. All widgets and
submissions are owned by exactly one tenant, enforced via foreign keys.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tenant(Base):
    """Multi-tenant root entity.

    Isolation guarantee:
        Every Widget row carries a ``tenant_id`` FK pointing back here.
        Every Submission row carries both a ``widget_id`` FK and a
        denormalized ``tenant_id`` FK for fast, join-free tenant scoping.

    Authentication:
        Management API callers supply ``X-Api-Key`` which is resolved to a
        Tenant row.  All subsequent queries are filtered by
        ``WHERE tenant_id = <resolved_tenant.id>``.
    """

    __tablename__ = "tenants"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),  # native_uuid=False → VARCHAR on SQLite
        primary_key=True,
        default=uuid.uuid4,
        comment="Stable UUID identifier for the tenant",
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Human-readable organisation name",
    )

    full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Personal full name of workspace account owner",
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Primary contact email for workspace owner",
    )

    website_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Company website URL",
    )

    industry: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Business industry or sector (e.g. Tech, E-commerce, Agency, Manufacturing, Other)",
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Business contact phone number",
    )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    api_key: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Hashed bearer token used for management API authentication",
    )

    # ------------------------------------------------------------------
    # Soft-delete / lifecycle
    # ------------------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Inactive tenants cannot create widgets or authenticate",
    )

    # ------------------------------------------------------------------
    # Audit timestamps
    # ------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Row creation timestamp (UTC)",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    widgets: Mapped[list["Widget"]] = relationship(  # noqa: F821
        "Widget",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="select",
    )
    submissions: Mapped[list["Submission"]] = relationship(  # noqa: F821
        "Submission",
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tenant id={self.id!s} name={self.name!r} active={self.is_active}>"
