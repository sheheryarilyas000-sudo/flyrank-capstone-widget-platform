"""
seed_and_run.py — Database seeder and local test environment initializer.

Actions performed:
  1. Creates all database tables if they do not exist.
  2. Creates a default Tenant if none exists, generating a secure API key.
  3. Creates a default Widget for that tenant if none exists.
  4. Updates test_site/index.html with the active Widget ID.
  5. Outputs credentials and test endpoints for local manual verification.
"""

import asyncio
from pathlib import Path
import re
import secrets
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal, Base, engine
import app.models  # noqa: F401 — registers all model classes on Base.metadata
from app.models.tenant import Tenant
from app.models.widget import Widget


async def seed_database() -> tuple[Tenant, Widget]:
    """Initialize tables and ensure dummy tenant and widget exist."""
    # 1. Create all tables in SQLite
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 2. Check or create Tenant
        stmt = select(Tenant).where(Tenant.name == "Acme Corporation")
        res = await session.execute(stmt)
        tenant = res.scalar_one_or_none()

        if not tenant:
            api_key = f"flk_live_{secrets.token_hex(16)}"
            tenant = Tenant(
                name="Acme Corporation",
                api_key=api_key,
                is_active=True,
            )
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)
            created_tenant = True
        else:
            created_tenant = False

        # 3. Check or create Widget for Tenant
        stmt = select(Widget).where(Widget.tenant_id == tenant.id)
        res = await session.execute(stmt)
        widget = res.scalar_one_or_none()

        if not widget:
            widget = Widget(
                tenant_id=tenant.id,
                name="Acme Main Lead Capture Form",
                config={
                    "title": "Join Acme Waitlist",
                    "submit_label": "Request Early Access",
                    "success_message": "Thanks! You're on the waitlist.",
                    "fields": [
                        {
                            "name": "full_name",
                            "type": "text",
                            "label": "Full Name",
                            "required": True,
                            "placeholder": "Jane Doe",
                        },
                        {
                            "name": "email",
                            "type": "email",
                            "label": "Work Email",
                            "required": True,
                            "placeholder": "jane@example.com",
                        },
                    ],
                },
                allowed_origins=["*"],
                is_active=True,
            )
            session.add(widget)
            await session.commit()
            await session.refresh(widget)
            created_widget = True
        else:
            created_widget = False

    return tenant, widget, created_tenant, created_widget


def update_test_page(widget_id: str) -> bool:
    """Inject the active Widget ID into test_site/index.html."""
    html_path = Path(__file__).parent / "test_site" / "index.html"
    if not html_path.exists():
        return False

    content = html_path.read_text(encoding="utf-8")

    # Replace widget ID occurrences in script tags and input values
    content = re.sub(
        r'widget\.js\?id=[^"\'>\s]+',
        f'widget.js?id={widget_id}',
        content,
    )
    content = re.sub(
        r'value="[0-9a-fA-F\-]{36}|YOUR_WIDGET_ID"',
        f'value="{widget_id}"',
        content,
    )

    html_path.write_text(content, encoding="utf-8")
    return True


async def main() -> None:
    print("=" * 65)
    print("  Flyrank Widget Platform — Database Seeder & Test Setup")
    print("=" * 65)

    try:
        tenant, widget, created_t, created_w = await seed_database()
    finally:
        await engine.dispose()

    # Update test_site/index.html with the active widget ID
    updated_html = update_test_page(str(widget.id))

    print("\n[✓] Database initialization complete.")
    if created_t:
        print("    - Created new Tenant: Acme Corporation")
    else:
        print("    - Found existing Tenant: Acme Corporation")

    if created_w:
        print("    - Created new Widget: Acme Main Lead Capture Form")
    else:
        print("    - Found existing Widget: Acme Main Lead Capture Form")

    if updated_html:
        print("    - Updated test_site/index.html with the Widget ID")

    print("\n" + "-" * 65)
    print("  CREDENTIALS & IDENTIFIERS")
    print("-" * 65)
    print(f"  Tenant Name   : {tenant.name}")
    print(f"  Tenant ID     : {tenant.id}")
    print(f"  Tenant API Key: {tenant.api_key}")
    print(f"  Widget ID     : {widget.id}")

    print("\n" + "-" * 65)
    print("  TEST ENDPOINTS (when server is running at http://localhost:8000)")
    print("-" * 65)
    print(f"  1. Widget Config     : GET  http://localhost:8000/api/widgets/{widget.id}/config")
    print(f"  2. Embed Loader      : GET  http://localhost:8000/widget.js?id={widget.id}")
    print(f"  3. Form Submission   : POST http://localhost:8000/submit/{widget.id}")
    print(f"  4. Dashboard Stats   : GET  http://localhost:8000/api/dashboard/stats")
    print(f"                         (Header: X-Api-Key: {tenant.api_key})")
    print("  5. Customer HTML Page: Open 'test_site/index.html' in your browser")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
