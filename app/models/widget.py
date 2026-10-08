"""
app/models/widget.py — Widget ORM model.

A Widget is a single embeddable lead-capture form.  It belongs to exactly
one Tenant via ``tenant_id``.  The widget's ``config`` JSON column drives
what fields are rendered by the embed script on external sites.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Widget(Base):
    """An embeddable form widget owned by a tenant.

    Multi-tenant isolation:
        ``tenant_id`` is a NOT NULL FK to ``tenants.id``.  All management API
        queries must include ``WHERE tenant_id = <authed_tenant_id>`` so that
        tenants cannot read or mutate each other's widgets.

    Public embed access:
        The public ``/embed/{widget_id}/config`` endpoint returns only the
        ``config`` JSON — no tenant identity is exposed.  The endpoint checks
        ``is_active`` and validates the caller's ``Origin`` header against
        ``allowed_origins``.

    SQLite compatibility:
        ``Uuid(native_uuid=False)`` stores UUIDs as VARCHAR(32) on SQLite.
        ``JSON`` replaces PostgreSQL-specific ``JSONB``; SQLAlchemy serialises
        the value to a JSON string automatically.
        ``allowed_origins`` uses ``JSON`` in place of ``ARRAY(Text)`` —
        stored as a JSON array string (e.g. ``'["https://mysite.com"]'``).
    """

    __tablename__ = "widgets"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid.uuid4,
        comment="Widget UUID — embedded in the <script> tag on external sites",
    )

    # ------------------------------------------------------------------
    # Ownership (multi-tenant isolation)
    # ------------------------------------------------------------------
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK to the owning tenant; all queries must scope by this column",
    )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Internal label visible only to the tenant (e.g. 'Homepage Hero Form')",
    )

    # ------------------------------------------------------------------
    # Form definition
    # ------------------------------------------------------------------
    config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment=(
            "Rendered form definition: title, submit_label, success_message, fields[]. "
            "See DESIGN.md §2.3 for the full schema."
        ),
    )

    # ------------------------------------------------------------------
    # CORS / origin validation
    # ------------------------------------------------------------------
    allowed_origins: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment=(
            "Allowlisted origins for CORS and Origin header validation. "
            "Stored as a JSON array. "
            "Example: ['https://mysite.com', 'https://staging.mysite.com']"
        ),
    )

    # ------------------------------------------------------------------
    # Soft-delete / lifecycle
    # ------------------------------------------------------------------
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Inactive widgets return 404 on public embed endpoints",
    )

    # ------------------------------------------------------------------
    # Audit timestamps
    # ------------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Updated automatically on every ORM flush",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    tenant: Mapped["Tenant"] = relationship(  # noqa: F821
        "Tenant",
        back_populates="widgets",
        lazy="select",
    )
    submissions: Mapped[list["Submission"]] = relationship(  # noqa: F821
        "Submission",
        back_populates="widget",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Widget id={self.id!s} name={self.name!r} "
            f"tenant_id={self.tenant_id!s} active={self.is_active}>"
        )
