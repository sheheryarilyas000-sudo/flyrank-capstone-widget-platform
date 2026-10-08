"""
app/models/submission.py — Submission ORM model.

A Submission records a single form fill from an external website visitor.
It is linked to both the Widget that was submitted and the owning Tenant
(denormalized) for fast, join-free tenant-scoped queries.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Submission(Base):
    """A single lead-capture form submission from an external visitor.

    Multi-tenant isolation:
        ``tenant_id`` is denormalized from the parent Widget so that a
        management API query ``SELECT * FROM submissions WHERE tenant_id = ?``
        never requires a JOIN through ``widgets``.  This also makes future
        Row-Level Security (RLS) policies straightforward.

    Data integrity:
        ``widget_id`` → ``widgets.id`` ensures every submission is traceable
        to its originating widget, even if the widget is later deactivated.
        ``tenant_id`` → ``tenants.id`` ensures cascade deletes work cleanly
        when a tenant is removed.

    SQLite compatibility:
        ``Uuid(native_uuid=False)`` stores UUIDs as VARCHAR(32) on SQLite.
        ``JSON`` replaces ``JSONB``.
        ``ip_address`` uses ``String(45)`` instead of PostgreSQL ``INET``
        (45 chars accommodates full IPv6 addresses).
    """

    __tablename__ = "submissions"

    # ------------------------------------------------------------------
    # Primary key
    # ------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ------------------------------------------------------------------
    # Ownership (multi-tenant isolation — denormalized)
    # ------------------------------------------------------------------
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment=(
            "Denormalized FK to the owning tenant. "
            "Enables fast tenant-scoped queries without JOIN through widgets."
        ),
    )

    # ------------------------------------------------------------------
    # Source widget
    # ------------------------------------------------------------------
    widget_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("widgets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK to the widget (form) that was submitted",
    )

    # ------------------------------------------------------------------
    # Submitted payload
    # ------------------------------------------------------------------
    data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Raw key/value pairs from the submitted form fields",
    )

    # ------------------------------------------------------------------
    # Extracted / enriched fields
    # ------------------------------------------------------------------
    submitter_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Extracted from data['email'] when present; enables fast email lookup",
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),   # 45 chars covers full IPv6; replaces PostgreSQL INET
        nullable=True,
        comment="Requester IP from X-Forwarded-For or direct connection",
    )

    country_code: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
        comment=(
            "ISO 3166-1 alpha-2 country code from geo-IP fallback chain. "
            "NULL when all providers fail or no key is configured."
        ),
    )

    # ------------------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------------------
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
        comment="UTC timestamp of the submission",
    )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------
    tenant: Mapped["Tenant"] = relationship(  # noqa: F821
        "Tenant",
        back_populates="submissions",
        lazy="select",
    )
    widget: Mapped["Widget"] = relationship(  # noqa: F821
        "Widget",
        back_populates="submissions",
        lazy="select",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Submission id={self.id!s} widget_id={self.widget_id!s} "
            f"email={self.submitter_email!r} at={self.submitted_at}>"
        )
