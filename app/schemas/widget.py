"""
app/schemas/widget.py — Pydantic schemas for widget CRUD operations.
"""

from typing import Any
import uuid

from pydantic import BaseModel, Field


class WidgetCreate(BaseModel):
    """Schema for creating a new embeddable widget with dynamic custom fields and lead magnet support."""
    name: str = Field(..., min_length=1, max_length=255, description="Widget internal name / label")
    config: dict[str, Any] = Field(
        default_factory=lambda: {
            "title": "Get in Touch",
            "subtitle": "",
            "submit_label": "Submit",
            "success_message": "Thanks! We will be in touch shortly.",
            "fields": [
                {"name": "full_name", "type": "text", "label": "Full Name", "required": True, "placeholder": "Jane Doe"},
                {"name": "email", "type": "email", "label": "Work Email", "required": True, "placeholder": "jane@company.com"},
                {"name": "phone", "type": "tel", "label": "Phone Number", "required": False, "placeholder": "+1 (555) 000-0000"},
                {"name": "company", "type": "text", "label": "Company Name", "required": False, "placeholder": "Demo Client Inc"},
                {"name": "service", "type": "select", "label": "Required Service", "required": False, "options": ["Enterprise SaaS", "Growth Consulting", "Custom Integration"]},
                {"name": "message", "type": "textarea", "label": "Project Details", "required": False, "placeholder": "Tell us about your requirements..."}
            ]
        },
        description="Dynamic form schema, lead magnet offer, and field definitions"
    )
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="List of allowed CORS origins"
    )


class WidgetUpdate(BaseModel):
    """Schema for updating an existing widget."""
    name: str | None = None
    config: dict[str, Any] | None = None
    allowed_origins: list[str] | None = None
    is_active: bool | None = None


class WidgetRead(BaseModel):
    """Schema for returning widget data."""
    id: str
    tenant_id: str
    name: str
    config: dict[str, Any]
    allowed_origins: list[str]
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {
        "from_attributes": True
    }
