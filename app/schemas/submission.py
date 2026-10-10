"""
app/schemas/submission.py — Pydantic schemas for the public submission endpoint.
"""

from typing import Any

from pydantic import BaseModel, Field


class SubmissionCreate(BaseModel):
    """Request body for POST /submit/{widget_id}.

    Sent by embed.js running on the visitor's browser.

    Fields
    ------
    data:
        Arbitrary key/value pairs from the rendered form fields.
        The keys must match the ``name`` attributes defined in the
        widget's ``config.fields`` array.
        Example: ``{"email": "user@example.com", "first_name": "Jane"}``

    honeypot:
        A hidden field that real users never see or fill in.
        Bots that auto-populate all form fields will fill this.
        If this field contains any non-empty value the submission is
        silently discarded — the bot receives a fake 200 OK so it does
        not know it was detected and does not retry.
    """

    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Submitted form field values (key = field name, value = user input).",
        examples=[{"email": "user@example.com", "first_name": "Jane"}],
    )

    honeypot: str = Field(
        default="",
        description=(
            "Spam-trap field — MUST be empty for legitimate submissions. "
            "Rendered as a hidden, off-screen input in embed.js so human "
            "visitors never interact with it."
        ),
    )

    model_config = {
        "extra": "allow",
        "json_schema_extra": {
            "examples": [
                {
                    "data": {
                        "email": "user@example.com",
                        "first_name": "Jane",
                        "phone": "+1 555-019-2834",
                        "lead_company": "Acme Corp",
                        "budget": "$10,000",
                    },
                    "honeypot": "",
                }
            ]
        },
    }


class SubmissionResponse(BaseModel):
    """Successful submission response body."""

    success: bool = True
