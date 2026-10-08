# BUILDLOG.md — AI-Assisted Development & Engineering Log

> **Project:** Flyrank Embeddable Widget & Lead-Capture Platform  
> **Course / Capstone:** B2B SaaS Backend Capstone  
> **Documentation Standard:** Section 11 AI-Usage Disclosure  

---

## 1. Overview of AI Pair Programming

Throughout this project, AI (Antigravity AI Assistant) was utilized as a senior pair programmer to accelerate scaffolding, design system architecture, enforce defensive backend patterns, and generate boilerplates. All code, design decisions, and architectural compromises were reviewed, validated, and directed by the engineer.

---

## 2. Phase-by-Phase Development Log

### Phase 1: Design & Project Foundation
- **Where AI Helped:**
  - Authored initial `DESIGN.md` specifying multi-tenant database models (`Tenant`, `Widget`, `Submission`), isolation invariants, and API contracts.
  - Drafted initial configuration and SQLAlchemy async ORM models.
  - Outlined the 4-step embed flow (`snippet` → `config` → `render` → `submit`).
- **What Human Engineer Changed / Directed:**
  - **Docker Pivot:** Directed AI to remove Docker Compose and PostgreSQL dependencies in favor of a zero-dependency local SQLite (`aiosqlite`) setup to meet strict $0 stack and environment constraints.
  - **Schema Adjustments:** Refactored PostgreSQL-specific types (`UUID`, `JSONB`, `ARRAY`, `INET`) into SQLite-portable equivalents (`Uuid(native_uuid=False)`, `JSON`, `String(45)`).
  - Explicitly defined non-goals (e.g., no visual drag-and-drop form builder UI).

---

### Phase 2: The Hardened Submission Path
- **Where AI Helped:**
  - Implemented the 9-step submission pipeline in `app/routers/submissions.py`.
  - Integrated `slowapi` for sliding-window IP rate limiting (10 req/min).
  - Created the geo-enrichment fallback chain (`ip-api.com` → `ipapi.co` → `None`) with short 2s timeouts and private IP short-circuiting.
  - Generated the anti-spam honeypot detection logic.
  - Implemented post-save fire-and-forget side effect logging (`send_webhook_or_email`) wrapped in broad exception isolation.
- **What Human Engineer Changed / Directed:**
  - Enforced that spam submissions triggering honeypots return a fake `200 OK` (silent drop) so scrapers/bots do not know they were filtered and do not retry.
  - Ensured network timeouts during geo-location lookup NEVER fail or crash the primary lead-capture transaction.
  - Directed that side-effect errors be logged but swallowed after DB commit to preserve 100% response reliability for legitimate visitors.

---

### Phase 3: Delivery, Dashboard & Verification
- **Where AI Helped:**
  - Implemented `GET /api/widgets/{widget_id}/config` with HTTP response caching (`Cache-Control: public, max-age=300`).
  - Implemented `GET /widget.js` bundle delivery with long-lived static cache headers (`Cache-Control: public, max-age=86400, immutable`).
  - Created authenticated `GET /api/dashboard/stats` reporting total submission volume and country breakdowns.
  - Built the simulated third-party customer test site in `test_site/index.html`.
  - Created `seed_and_run.py` to auto-initialize SQLite, generate active tenant credentials, seed widget definitions, and update the test page script tag.
- **What Human Engineer Changed / Directed:**
  - Required absolute tenant isolation in the dashboard endpoint via strict `WHERE tenant_id = <current_tenant.id>` SQL conditions.
  - Added CORS configuration (`allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`) to accommodate browser preflight `OPTIONS` requests from any external host.
  - Separated test site from backend code to accurately simulate cross-origin requests.

---

## 3. Tool & AI Usage Summary

| Category | AI Contribution | Human Engineering Oversight |
|---|---|---|
| **System Architecture** | Initial entity design, flow diagrams, API contract blueprints | Enforced multi-tenant isolation rules, strict $0 local dependencies |
| **Code Generation** | FastAPI route scaffolding, SQLAlchemy async setup, slowapi wiring | Code reviews, type annotations, error code consistency, edge case fixes |
| **Security & Spam** | Honeypot field handling, client IP extraction via `X-Forwarded-For` | Configured silent discard behavior and rate-limit error response formats |
| **Resilience & Fallbacks**| Geo-IP provider fallback chain, async HTTP client setup | Verified timeout limits and failure-isolation boundaries |
| **Verification & Tooling** | `seed_and_run.py`, `test_site/index.html`, `capstone.yaml` | Execution planning, manual validation, test verification |

---

## 4. Key Engineering Insights & Lessons Learned

1. **Defensive Endpoint Design:** A public form submission endpoint on the internet is an open attack surface. Combining client-side honeypots, server-side IP rate limiting, and origin headers provides multi-layer protection without frustrating real human users.
2. **Third-Party Dependency Isolation:** External enrichments (like IP geo-location APIs) are inherently unreliable. Treating them as non-blocking, best-effort enrichments with tight timeouts (2s) ensures platform availability even during upstream outages.
3. **Database Portability:** Moving from PostgreSQL to SQLite in SQLAlchemy 2.0 requires careful selection of portable column types (`Uuid(native_uuid=False)` and `JSON`) while preserving type safety.
