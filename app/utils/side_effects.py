"""
app/utils/side_effects.py — Post-save notification side effects.

These functions are called AFTER a submission has been successfully committed
to the database.  They are always wrapped in a broad try/except by the caller
so that ANY exception here is logged and swallowed — the visitor always
receives their 200 OK regardless of what happens in this module.

Current implementation: console logging only (simulates the action).
Future phases will replace the bodies with:
  - HTTP POST to the tenant's configured webhook URL
  - Email dispatch via SendGrid / AWS SES / Resend
  - Push to a message queue (e.g. Redis Streams, SQS)
"""

import logging

logger = logging.getLogger(__name__)


async def send_webhook_or_email(submission: object) -> None:
    """Simulate a post-save notification after a new submission is recorded.

    Parameters
    ----------
    submission:
        A ``Submission`` ORM instance.  Typed as ``object`` here to avoid a
        circular import — in practice this is always ``app.models.Submission``.

    Raises
    ------
    This function MAY raise any exception.  The caller is responsible for
    catching and logging it so the HTTP response is never affected.
    """
    # ------------------------------------------------------------------
    # Simulate the side effect with a structured log line.
    # Replace this block in Phase 3 with real webhook / email dispatch.
    # ------------------------------------------------------------------
    logger.info(
        "[SIDE EFFECT] New submission — id=%s | widget=%s | tenant=%s | email=%s | country=%s",
        getattr(submission, "id", "?"),
        getattr(submission, "widget_id", "?"),
        getattr(submission, "tenant_id", "?"),
        getattr(submission, "submitter_email", None) or "(none)",
        getattr(submission, "country_code", None) or "(unknown)",
    )

    # Example of how a future webhook call would look:
    #
    #   async with httpx.AsyncClient(timeout=5.0) as client:
    #       await client.post(
    #           tenant.webhook_url,
    #           json={"submission_id": str(submission.id), "data": submission.data},
    #       )
