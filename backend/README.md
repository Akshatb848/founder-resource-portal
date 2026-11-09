# Founder's Resource Portal — API

FastAPI service for the portal (Python 3.11+, PostgreSQL 14+). See the [main README](../README.md) for setup.

| Path | Purpose |
|---|---|
| `main.py` | API: auth, founder endpoints, request queue, content governance, intake; serves `dist/` only |
| `admin_api.py`, `talent_api.py`, `profile_api.py`, `messages_api.py`, `chat_api.py`, `lms_api.py`, `engagement_api.py`, `crm_api.py`, `news_api.py`, `otp_api.py` | Feature routers |
| `permissions.py` | Roles and permissions: the single source of truth, synced to the database at start-up |
| `security.py`, `auth_store.py` | Sessions, permission checks, lockout, security headers |
| `config.py` | Environment settings (`APP_ENV`, `PG_*`, feature switches, limits) |
| `schema.sql` | Schema + idempotent migrations |
| `seed.py`, `seed_portfolio.py` | Fictional demo companies, people and content (upsert, safe to re-run) |
| `alpha_catalog.py`, `lms_content.py`, `playbook.py` | Resource catalog, starter lessons, 100-day playbook |
| `news_feed.py` | Optional RSS reader (https + public-IP only; off by default) |
| `data/` | Fictional demo portfolio, Connect directory and sector briefs |
| `scripts/build_alpha_content.py` | Generates the XLSX/DOCX templates in `content/alpha/` |
| `scripts/import_*.py` | Load the demo portfolio, Connect directory and sector briefs (dry run unless `--apply`) |
| `scripts/provision_company.py`, `scripts/create_super_admin.py` | Add a company and its founders; create the Super Admin |
| `scripts/reset_demo_data.py`, `scripts/remove_samples.py` | Clear demo activity / sample rows (refuse real-data databases) |

Health: `GET /api/health` · API docs (non-production only): `/api/docs`.
