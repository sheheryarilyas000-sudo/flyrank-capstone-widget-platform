# Flyrank — Embeddable Widget & Lead-Capture Platform

> A production-hardened B2B SaaS backend that lets customers create embeddable signup-form widgets and install them on any external website via a single `<script>` tag.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Setup & Quick Start](#setup--quick-start)
4. [Project Structure](#project-structure)
5. [API Reference & Route Map](#api-reference--route-map)
6. [Security & Resilience Features](#security--resilience-features)
7. [Capstone Evaluation Artifacts](#capstone-evaluation-artifacts)
8. [Honest Limitations Note](#honest-limitations-note)

---

## Project Overview

Flyrank Widget Platform provides an end-to-end embeddable lead-capture infrastructure:

- **Embed Delivery**: Delivers `<script>` loader bundles and widget configuration JSON with HTTP caching headers (`Cache-Control`).
- **Hardened Ingestion**: Ingests submissions from third-party cross-origin domains with full CORS preflight support, IP rate limiting, anti-spam honeypot detection, and non-blocking geo-location enrichments.
- **Multi-Tenant Isolation**: Customers (tenants) authenticate using an API key (`X-Api-Key`). All queries and analytics strictly filter by `tenant_id`.
- **Zero-Dollar Tech Stack**: Pure Python (FastAPI), SQLite (`aiosqlite`) via SQLAlchemy 2.0 async engine, and Vanilla HTML/JS frontend test site. No Docker required.

---

## Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                        EXTERNAL CLIENT BROWSER / THIRD-PARTY SITE                 |
|                               (e.g., test_site/index.html)                        |
+-----------------------------------------------------------------------------------+
             |                                                |
  1. GET /widget.js?id=<id>                        3. POST /submit/<id>
  2. GET /api/widgets/<id>/config                     (CORS Preflight + Payload)
             |                                                |
             v                                                v
+-----------------------------------------------------------------------------------+
|                                FASTAPI BACKEND APP                                |
|                                                                                   |
|  [Delivery Pipeline]                           [Hardened Ingestion Pipeline]      |
|  - GET /widget.js (Cache: 86400s)              - CORS Middleware (* origins)      |
|  - GET /api/widgets/<id>/config (Cache: 300s)  - Rate Limiter (10 req/min via IP) |
|                                                - Honeypot Trap (Silent 200 drop)  |
|  [Tenant Dashboard API]                        - UUID Format & Existence Check    |
|  - GET /api/dashboard/stats                    - Client IP Extraction             |
|    Auth: X-Api-Key                             - Safe Side-Effect Notification    |
+-----------------------------------------------------------------------------------+
             |                                     |                   |
             |                                     |                   | Best-effort
             v                                     v                   v Geo-IP Fallback
+--------------------------+         +--------------------------+   +-------------------+
|     SQLITE DATABASE      |         |  POST-SAVE SIDE EFFECTS  |   | 1. ip-api.com     |
|      (database.db)       |         |  (send_webhook_or_email) |   | 2. ipapi.co       |
|                          |         |                          |   | 3. NULL fallback  |
|  - tenants               |         |  * Isolated in broad     |   +-------------------+
|  - widgets               |         |    try/except block      |
|  - submissions           |         |  * Never crashes request |
+--------------------------+         +--------------------------+
```

---

## Setup & Quick Start

### 1. Prerequisites
- Python 3.11+ (or 3.12+)
- `pip` or virtual environment tool

### 2. Virtual Environment Setup

```bash
# Clone and enter directory
cd flyrank-capstone-widget-platform

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (cmd):
.\.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Initialize & Seed Database

Run the automated seeder script to initialize tables, create a default tenant and widget, and inject the generated Widget ID into `test_site/index.html`:

```bash
python seed_and_run.py
```

This will print the generated **Tenant API Key** and **Widget ID** to the terminal.

### 4. Run the API Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API Base URL: `http://localhost:8000`
- Interactive Swagger UI: `http://localhost:8000/docs`

### 5. Verify the Client Test Site

Open [`test_site/index.html`](test_site/index.html) directly in any web browser. It contains an external form embedding the widget tag and allows sending live test submissions to the backend.

---

## Project Structure

```
flyrank-capstone-widget-platform/
├── app/
│   ├── main.py                  # FastAPI entry point, CORS & middleware wiring
│   ├── config.py                # App configuration (Pydantic BaseSettings)
│   ├── database.py              # Async SQLAlchemy engine & session factory
│   ├── models/
│   │   ├── __init__.py          # Model exports for table creation
│   │   ├── tenant.py            # Tenant ORM model
│   │   ├── widget.py            # Widget ORM model
│   │   └── submission.py        # Submission ORM model
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── dashboard.py         # Authenticated owner analytics (GET /api/dashboard/stats)
│   │   ├── embed.py             # Widget bundle & config delivery (GET /widget.js, /api/widgets/../config)
│   │   ├── submissions.py       # Public submission endpoint (POST /submit/{id})
│   │   └── widgets.py           # Widget CRUD router skeleton
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── submission.py        # Pydantic submission schema & honeypot definition
│   └── utils/
│       ├── __init__.py
│       ├── auth.py              # X-Api-Key tenant authentication dependency
│       ├── geo.py               # Two-provider Geo-IP fallback chain (2s timeout)
│       ├── limiter.py           # slowapi rate limiter singleton
│       └── side_effects.py      # Isolated post-save notification stub
├── test_site/
│   └── index.html               # External customer page with embed <script> tag
├── capstone.yaml                # Evaluator run & seed manifest
├── DESIGN.md                    # System architecture & database model specification
├── EVIDENCE.md                  # Section 6 evaluation checklist & test proof placeholders
├── BUILDLOG.md                  # AI pair programming log & technical decisions
├── seed_and_run.py              # Automated database setup & seeder
├── requirements.txt             # Python dependencies
└── README.md
```

---

## API Reference & Route Map

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/widget.js?id={widget_id}` | None (Public) | Delivers embed JavaScript loader bundle (`Cache-Control: 86400s`) |
| `GET` | `/api/widgets/{widget_id}/config` | None (Public) | Delivers form configuration JSON (`Cache-Control: 300s`) |
| `POST`| `/submit/{widget_id}` | None (Public) | Accepts lead submissions (Rate limit: 10/min, Honeypot protected) |
| `POST`| `/api/submissions/{widget_id}` | None (Public) | API alias for form submission |
| `GET` | `/api/dashboard/stats` | `X-Api-Key` | Tenant metrics: total submissions count & geo-breakdown |
| `GET` | `/health` | None (Ops) | API liveness probe |

---

## Security & Resilience Features

1. **Browser Preflight & CORS**: Handles cross-origin requests (`allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`) so external customer sites can embed and submit without CORS blocking.
2. **IP Rate Limiting**: Powered by `slowapi` with a sliding 10 requests/minute per client IP to stop flood attacks (returns HTTP 429).
3. **Anti-Spam Honeypot Trap**: Invisible field `honeypot` traps automated bots. Requests with a filled honeypot return a fake `200 OK` without touching the database.
4. **Geo-Location Fallback Chain**: Tries `ip-api.com` → `ipapi.co` → `NULL`. Wrapped in tight 2-second timeouts and try/except blocks to guarantee external API lag never degrades the submission endpoint.
5. **Safe Side-Effect Isolation**: Post-save actions (webhooks, email notifications) run in isolated exception handlers; downstream network errors never invalidate a successful database save.
6. **Multi-Tenant Isolation**: Queries require an active `X-Api-Key` and enforce `WHERE tenant_id = <current_tenant.id>`.

---

## Capstone Evaluation Artifacts

- **Manifest**: [`capstone.yaml`](capstone.yaml) — Contains `run:`, `seed:`, and `base url:` properties.
- **Evidence Checklist**: [`EVIDENCE.md`](EVIDENCE.md) — Checklists and output placeholders for Section 6 verification.
- **AI Build Log**: [`BUILDLOG.md`](BUILDLOG.md) — Documentation of AI usage, architectural decisions, and engineer overrides.
- **Design Spec**: [`DESIGN.md`](DESIGN.md) — Original database models and architecture decisions.

---

## Honest Limitations Note

In keeping with the capstone evaluation standards and engineering honesty:

1. **SQLite in Place of PostgreSQL**:
   - To guarantee a strict $0 local development environment and eliminate third-party daemon/container prerequisites (such as Docker), this project was transitioned to local SQLite via `aiosqlite`.
   - SQLite provides complete ACID compliance, async query execution, and portability for local testing and evaluation. However, in high-concurrency production deployments requiring horizontal read scaling, connection pooling, and multi-writer performance, a managed PostgreSQL cluster with pgvector/JSONB indexing would be the recommended target database.

2. **`Base.metadata.create_all` Instead of Alembic Migrations**:
   - For local evaluation simplicity and zero-friction one-command setup (`seed_and_run.py`), database tables are initialized directly via SQLAlchemy's `Base.metadata.create_all`.
   - In an enterprise production lifecycle with evolving schemas, zero-downtime deployments, and rolling rollbacks, version-controlled database migrations via Alembic (`alembic upgrade head`) should be introduced.
