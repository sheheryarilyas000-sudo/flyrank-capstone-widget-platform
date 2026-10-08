# DESIGN.md — Flyrank Embeddable Widget & Lead-Capture Platform

> **Status:** Phase 1 — Design & Project Setup  
> **Author:** Senior Backend Engineering  
> **Last Updated:** 2026-10-07

---

## Table of Contents

1. [Goals & Non-Goals](#1-goals--non-goals)
2. [Database Models](#2-database-models)
3. [Multi-Tenant Isolation Strategy](#3-multi-tenant-isolation-strategy)
4. [The Embed Flow](#4-the-embed-flow)
5. [API Contracts](#5-api-contracts)
6. [Security Considerations](#6-security-considerations)
7. [Failure & Fallback Strategy](#7-failure--fallback-strategy)

---

## 1. Goals & Non-Goals

### Goals (In Scope)

- **Multi-tenant widget management**: Each tenant can create, update, and delete their own widgets only.
- **Public embed delivery**: A lightweight JS snippet fetches widget config and renders a form on any external domain.
- **Secure public submission endpoint**: Handles CORS preflight, rate limiting (per IP), honeypot spam protection, and idempotent writes.
- **IP geo-location tagging**: Best-effort geo-tagging of submissions with a graceful fallback chain (provider A → provider B → null).
- **Strict data isolation**: A tenant's submissions and widgets are never visible to another tenant at the database query level.

### Non-Goals (Explicitly Out of Scope)

- ❌ **No drag-and-drop form builder UI.** Widget configuration is done via API JSON payloads. The rendered form follows a fixed schema (label, placeholder, field type). A visual builder is a future product decision.
- ❌ No real-time submission streaming or webhooks (Phase 1).
- ❌ No email notifications on submission (Phase 1).
- ❌ No tenant self-service signup/billing (tenants are seeded manually for now).

---

## 2. Database Models

### 2.1 Entity Relationship Overview

```
┌─────────────┐        ┌──────────────┐        ┌─────────────────┐
│   tenants   │──1:N──>│   widgets    │──1:N──>│   submissions   │
│─────────────│        │──────────────│        │─────────────────│
│ id (PK)     │        │ id (PK)      │        │ id (PK)         │
│ name        │        │ tenant_id FK │        │ widget_id FK    │
│ api_key     │        │ name         │        │ tenant_id FK    │
│ is_active   │        │ config JSON  │        │ data JSON       │
│ created_at  │        │ allowed_     │        │ submitter_email │
│             │        │  origins []  │        │ ip_address      │
│             │        │ is_active    │        │ country_code    │
│             │        │ created_at   │        │ submitted_at    │
│             │        │ updated_at   │        │                 │
└─────────────┘        └──────────────┘        └─────────────────┘
```

---

### 2.2 `tenants` Table

Represents a paying customer of the platform.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `UUID` | PK, default gen | Stable identifier |
| `name` | `VARCHAR(255)` | NOT NULL | Human-readable org name |
| `api_key` | `VARCHAR(64)` | UNIQUE, NOT NULL | Hashed bearer token for management API auth |
| `is_active` | `BOOLEAN` | NOT NULL, default `true` | Soft-disable a tenant without deletion |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, default now | Audit trail |

**Isolation rule:** All management API routes first resolve the authenticated tenant from `api_key` and only query child tables with `WHERE tenant_id = <resolved_id>`.

---

### 2.3 `widgets` Table

A single embeddable form belonging to exactly one tenant.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `UUID` | PK, default gen | Used in the embed `<script>` tag |
| `tenant_id` | `UUID` | FK → `tenants.id`, NOT NULL | Enforces ownership |
| `name` | `VARCHAR(255)` | NOT NULL | Internal label (e.g. "Homepage Hero Form") |
| `config` | `JSONB` | NOT NULL | Rendered form definition (see schema below) |
| `allowed_origins` | `TEXT[]` | NOT NULL, default `{}` | Allowlist for CORS + origin validation |
| `is_active` | `BOOLEAN` | NOT NULL, default `true` | Inactive widgets return 404 on embed |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, default now | Audit |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, default now | Updated via trigger or ORM |

**Widget `config` JSONB schema (example):**

```jsonc
{
  "title": "Get Early Access",
  "submit_label": "Join Waitlist",
  "success_message": "Thanks! We'll be in touch.",
  "fields": [
    { "name": "email",      "type": "email",  "label": "Email",      "required": true,  "placeholder": "you@example.com" },
    { "name": "first_name", "type": "text",   "label": "First Name", "required": false, "placeholder": "Jane" }
  ]
}
```

---

### 2.4 `submissions` Table

A single form submission captured from an external website.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `UUID` | PK, default gen | |
| `widget_id` | `UUID` | FK → `widgets.id`, NOT NULL | Which form was submitted |
| `tenant_id` | `UUID` | FK → `tenants.id`, NOT NULL | **Denormalized** for fast tenant-scoped queries without join |
| `data` | `JSONB` | NOT NULL | Raw field key/value from submitted form |
| `submitter_email` | `VARCHAR(255)` | NULLABLE | Extracted from `data` if an `email` field exists |
| `ip_address` | `INET` | NULLABLE | Requester IP (from `X-Forwarded-For` or direct) |
| `country_code` | `CHAR(2)` | NULLABLE | ISO 3166-1 alpha-2, from geo-IP fallback chain |
| `submitted_at` | `TIMESTAMPTZ` | NOT NULL, default now | |

> **Why denormalize `tenant_id` on submissions?**  
> Fetching all submissions for a tenant (`WHERE tenant_id = ?`) avoids a join through `widgets`. It also makes row-level security policies simpler if we add PostgreSQL RLS in a future phase.

---

## 3. Multi-Tenant Isolation Strategy

Isolation is enforced at **three layers**:

| Layer | Mechanism |
|---|---|
| **Authentication** | Every management API request carries an `X-Api-Key` header. The middleware resolves this to a `tenant` row and stores it in request state. |
| **Query layer** | Every ORM query on `widgets` and `submissions` includes `WHERE tenant_id = <current_tenant.id>`. No raw queries bypass this. |
| **Public embed** | The public `/embed/{widget_id}` and `/submit/{widget_id}` endpoints do **not** expose any tenant identity. They only check `widget.is_active` and the widget's own `allowed_origins` list. |

A tenant can never enumerate or access another tenant's widget UUIDs through the management API because the UUID alone is insufficient — the API key must also resolve to the owning tenant.

---

## 4. The Embed Flow

```
Step 1 — Snippet Install
  Customer pastes into their HTML:
    <script src="https://api.flyrank.io/static/embed.js"
            data-widget-id="<widget-uuid>"></script>

Step 2 — Config Fetch (embed.js runs)
  GET /embed/<widget-uuid>/config
  ← 200 { title, fields, submit_label, success_message }
  (CORS: allowed_origins validated; inactive widget → 404)

Step 3 — Form Render
  embed.js injects a <form> into the page DOM using the config JSON.
  No iframes. No external CSS dependencies.

Step 4 — Submission
  Visitor fills form and clicks submit.
  embed.js fires:
    POST /submit/<widget-uuid>
    Origin: <external site origin>
    Body: { "email": "...", "first_name": "..." }
          + honeypot field (hidden, must be empty)

  Backend pipeline:
    a. CORS preflight validation (Origin in widget.allowed_origins)
    b. Rate limit check (10 req/min per IP, sliding window)
    c. Honeypot assertion (reject if filled)
    d. Pydantic schema validation
    e. INSERT into submissions
    f. Best-effort geo-IP lookup (provider A → B → null on failure)
    g. Return { "success": true } or structured error JSON
```

---

## 5. API Contracts

All management routes require `X-Api-Key: <tenant_api_key>` header.  
All responses are `application/json`.

### 5.1 Widget Management (Private — Tenant API Key Required)

| Method | Path | Description | Auth |
|---|---|---|---|
| `POST` | `/api/v1/widgets` | Create a new widget | ✅ Required |
| `GET` | `/api/v1/widgets` | List all widgets for the authed tenant | ✅ Required |
| `GET` | `/api/v1/widgets/{widget_id}` | Get a single widget (must belong to tenant) | ✅ Required |
| `PATCH` | `/api/v1/widgets/{widget_id}` | Update widget name, config, or allowed_origins | ✅ Required |
| `DELETE` | `/api/v1/widgets/{widget_id}` | Soft-delete (sets `is_active=false`) | ✅ Required |

**`POST /api/v1/widgets` — Request body:**
```json
{
  "name": "Homepage Hero Form",
  "allowed_origins": ["https://mysite.com"],
  "config": {
    "title": "Get Early Access",
    "submit_label": "Join Waitlist",
    "success_message": "Thanks!",
    "fields": [
      { "name": "email", "type": "email", "label": "Email", "required": true, "placeholder": "you@example.com" }
    ]
  }
}
```

**Response `201 Created`:**
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "name": "Homepage Hero Form",
  "allowed_origins": ["https://mysite.com"],
  "config": { "..." },
  "is_active": true,
  "created_at": "2026-10-07T00:00:00Z",
  "updated_at": "2026-10-07T00:00:00Z"
}
```

---

### 5.2 Submission Management (Private — Tenant API Key Required)

| Method | Path | Description | Auth |
|---|---|---|---|
| `GET` | `/api/v1/widgets/{widget_id}/submissions` | List all submissions for a widget | ✅ Required |
| `GET` | `/api/v1/submissions/{submission_id}` | Get a single submission by ID | ✅ Required |

---

### 5.3 Public Embed Endpoints (No Auth — CORS Enforced)

| Method | Path | Description |
|---|---|---|
| `GET` | `/embed/{widget_id}/config` | Deliver widget config JSON to the embed script |
| `POST` | `/submit/{widget_id}` | Accept a form submission from an external origin |
| `OPTIONS` | `/submit/{widget_id}` | CORS preflight handler |

**`GET /embed/{widget_id}/config` — Response `200 OK`:**
```json
{
  "title": "Get Early Access",
  "submit_label": "Join Waitlist",
  "success_message": "Thanks!",
  "fields": [...]
}
```
- Returns `404` if widget does not exist or `is_active=false`.
- No tenant data is exposed.

**`POST /submit/{widget_id}` — Request:**
```json
{
  "data": { "email": "user@example.com", "first_name": "Jane" },
  "_honeypot": ""
}
```

**Response `200 OK`:**
```json
{ "success": true }
```

**Error responses:**
```json
{ "success": false, "error": "rate_limit_exceeded" }
{ "success": false, "error": "spam_detected" }
{ "success": false, "error": "validation_error", "detail": [...] }
{ "success": false, "error": "widget_not_found" }
```

---

## 6. Security Considerations

| Threat | Mitigation |
|---|---|
| Cross-origin abuse | `allowed_origins` per widget; strict CORS enforcement rejects unlisted origins |
| Submission spam | Honeypot hidden field + rate limiting (sliding window, per-IP) |
| Tenant data leakage | All management queries scoped by `tenant_id`; UUIDs alone grant no access |
| API key exposure | Keys stored as bcrypt hashes; `.env` never committed |
| SQL injection | SQLAlchemy ORM with parameterized queries only; no raw string interpolation |
| Large payloads | `data` JSONB capped at validation layer (Pydantic max-length per field) |

---

## 7. Failure & Fallback Strategy

### Geo-IP Fallback Chain

```
Request arrives
    │
    ▼
Try Provider A (ipapi.co) ──success──> tag country_code, continue
    │ failure / timeout (2s)
    ▼
Try Provider B (ipstack.com) ──success──> tag country_code, continue
    │ failure / timeout (2s)
    ▼
country_code = NULL ──────────────────> submission saved without geo tag
```

The submission is **always saved** regardless of geo-IP status. Geo-tagging is a best-effort enrichment, not a hard dependency.

### Database Unavailability

- FastAPI lifespan event validates DB connectivity at startup.
- If the DB is unreachable during a submission, the endpoint returns `503 Service Unavailable` with a retry-after header. The embed.js client surfaces a generic "Please try again" message to the visitor.
