"""Founder's Resource Portal API, alpha.

Backend and frontend are separate: this service exposes /api/* and serves only the built
frontend in FRONTEND_DIR (dist/). Resource files are served through authenticated endpoints only.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from psycopg_pool import PoolTimeout
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

import os
from logging.handlers import RotatingFileHandler

from backend.admin_api import _audit, person_timeline, read_csv_upload, router as admin_router
from backend.crm_api import check_staff_name, router as crm_router
from backend.engagement_api import router as engagement_router
from backend.news_api import router as news_router
from backend.talent_api import router as talent_router
from backend.messages_api import router as messages_router
from backend.lms_api import router as lms_router
from backend.profile_api import router as profile_router
from backend.otp_api import router as otp_router
from backend.chat_api import router as chat_router  # noqa: E402
from backend.news_feed import start_scheduler, stop_scheduler
from backend.permissions import PERMISSIONS, ROLES, sync_access_model
from backend.alpha_catalog import PRIORITY_TO_CATEGORY, PRIORITY_TO_TAGS
from backend.auth_store import create_session, load_access, revoke_session
from backend.security import (
    auth_session,
    has_perm,
    iso,
    require_founder,
    require_founder_or_preview,
    company_scope,
    founder_company,
    preview_request,
    require_perm,
)
from backend.config import (
    ALLOWED_ORIGINS,
    APP_ENV,
    CONTENT_DIR,
    FRONTEND_DIR,
    LOGIN_LOCKOUT_MINUTES,
    LOGIN_MAX_FAILURES,
    MAX_UPLOAD_MB,
    POSTGRES_CONFIG,
    UPLOAD_DIR,
)
from backend.audience import Audience, clean_audience, describe, visible
from backend.data_mode import data_mode
from backend.messaging import company_team, deliver_later, notify, workspace_link
from backend.db import close_pool, db_label, get_conn, open_pool
from backend.sqlutil import q

# The released version lives in the VERSION file at the repository root (bumped at each release).
_version_file = Path(__file__).resolve().parents[1] / "VERSION"
APP_VERSION = _version_file.read_text(encoding="utf-8").strip() if _version_file.exists() else "dev"


def _sync_permissions() -> None:
    """Make the roles/permissions tables match backend/permissions.py (the code is the source of truth)."""
    try:
        # A direct connection (not the pool): at start-up the pool may still be opening its connections.
        with get_conn(POSTGRES_CONFIG["dbname"]) as conn:
            with conn.cursor() as cur:
                sync_access_model(cur)
            conn.commit()
    except Exception:  # database not migrated yet: run `python -m backend.seed`
        logging.getLogger("founder_portal").exception("Could not sync roles and permissions")


@asynccontextmanager
async def lifespan(_app):
    _file_logging()
    open_pool()  # reuse database connections across requests
    _sync_permissions()
    start_scheduler()  # live sector news: approved feeds every NEWS_FETCH_MINUTES (off with NEWS_FETCH_ENABLED=0)
    yield
    stop_scheduler()
    close_pool()


def _file_logging() -> None:
    """On a server (LOG_FILE set by the deployment): keep warnings and errors, including the traceback of any
    request that fails, in a rotating file (5 x 10 MB). Request bodies, passwords and tokens are never logged."""
    path = os.getenv("LOG_FILE", "").strip()
    if not path:
        return
    for name in ("founder_portal", "uvicorn.error"):
        if any(isinstance(h, RotatingFileHandler) for h in logging.getLogger(name).handlers):
            return
    handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for name in ("founder_portal", "uvicorn.error"):
        logging.getLogger(name).addHandler(handler)


app = FastAPI(
    title="Founder's Resource Portal API",
    version=APP_VERSION,
    docs_url=None if APP_ENV == "production" else "/api/docs",
    redoc_url=None,
    openapi_url=None if APP_ENV == "production" else "/api/openapi.json",
    lifespan=lifespan,
)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.exception_handler(PoolTimeout)
async def portal_busy(_request: Request, _exc: PoolTimeout) -> JSONResponse:
    """Every database connection stayed in use for PG_POOL_WAIT_SECONDS: answer quickly instead of hanging.
    The browser retries reads once by itself (api-integration.js)."""
    logging.getLogger("founder_portal").warning("portal busy: no free database connection")
    return JSONResponse(status_code=503, headers={"Retry-After": "2"},
                        content={"detail": "The portal is very busy right now. Please try again in a moment."})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Staff previewing the founder portal say which company with X-Preview-Company (checked in founder_company).
    raw = request.headers.get("x-preview-company", "")
    preview_request.set(int(raw) if raw.isdigit() else None)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
    )
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif request.url.path == "/" or request.url.path.endswith(".html"):
        # Pages always revalidate so a release is picked up at once; scripts/styles carry ?v= versions.
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


RESOURCE_STATUSES = ("in_review", "approved", "rejected", "archived")
ALLOWED_UPLOAD_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".csv"}


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class HelpBody(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    context: str = Field(min_length=1, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    resource_id: int | None = None
    connect_entry_id: int | None = None


class IntakeBody(BaseModel):
    """Founder questionnaire (meeting 23 Oct 2026: keep founders' questions to a minimum). The company's stage,
    sector and other details are set by Demo Ventures in the company record; these fields remain optional so
    earlier answers stay readable."""
    priorities: list[str] = Field(min_length=1, max_length=3)
    fundraising: str = Field(max_length=60)
    blocker: str | None = Field(default=None, max_length=1000)
    stage: str | None = Field(default=None, max_length=60)
    business_model: str | None = Field(default=None, max_length=60)
    team_size: str | None = Field(default=None, max_length=40)
    tools: list[str] = Field(default_factory=list, max_length=10)


class ResourceReview(BaseModel):
    action: str  # approve | reject | archive | resubmit
    comment: str | None = Field(default=None, max_length=1000)


def _login_redirect(user: dict[str, Any]) -> str:
    """One sign-in page for everyone; the account decides where it lands (21 Oct 2026 decision)."""
    return "/" if user["account_type"] == "founder" else "/analyst.html"


@app.get("/admin", include_in_schema=False)
def admin_portal() -> RedirectResponse:
    """Old address. There is one sign-in page for everyone now."""
    return RedirectResponse("/", status_code=307)


def effective_company_id(user: dict[str, Any]) -> int:
    """The founder's own company, or the company a staff member is previewing (security.founder_company)."""
    return founder_company(user)[0]


_iso = iso


def _resource_path(file_name: str | None) -> Path | None:
    """Resolve a resource file strictly inside CONTENT_DIR (no path traversal)."""
    if not file_name:
        return None
    for base in (CONTENT_DIR / "alpha", UPLOAD_DIR):
        candidate = (base / file_name).resolve()
        if candidate.is_file() and base.resolve() in candidate.parents:
            return candidate
    return None


@app.get("/api/health")
def health() -> dict[str, Any]:
    db_ok = True
    mode = "unknown"
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                mode = data_mode(cur)  # "real" or "demo": the smoke test refuses to run against real data
    except Exception:  # noqa: BLE001, health must report, not raise
        logging.getLogger("founder_portal").warning("health check: database query failed", exc_info=True)
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "founder-resource-portal",
        "phase": "alpha",
        "version": APP_VERSION,
        "environment": APP_ENV,
        "database": db_label() if db_ok else "unreachable",
        "data": mode,
    }


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    email = body.email.lower()
    client = request.client.host if request.client else "unknown"  # a lock applies to one device, not the whole account
    since = datetime.now(timezone.utc) - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q("SELECT COUNT(*) FROM login_failures WHERE email = %s AND COALESCE(client, '') = %s AND created_at > %s"),
                (email, client, since),
            )
            if cur.fetchone()[0] >= LOGIN_MAX_FAILURES:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many failed attempts. Try again in {LOGIN_LOCKOUT_MINUTES} minutes.",
                )
            cur.execute(
                q(
                    """
                SELECT u.id, u.email, u.password_hash, u.full_name, u.account_type, u.company_id,
                       c.name AS company_name, c.sector
                FROM users u
                LEFT JOIN companies c ON c.id = u.company_id
                WHERE u.email = %s AND u.active IS TRUE
                """
                ),
                (email,),
            )
            row = cur.fetchone()
            if not row or not bcrypt.checkpw(body.password.encode(), row[2].encode()):
                cur.execute(q("INSERT INTO login_failures (email, client) VALUES (%s, %s)"), (email, client))
                cur.execute(
                    q("INSERT INTO admin_audit (actor, action, target, details, company_id) VALUES (%s, 'login.failed', %s, %s, %s)"),
                    (email, email, json.dumps({"device": client}), row[5] if row else None),
                )
                conn.commit()
                raise HTTPException(status_code=401, detail="Invalid email or password")
            cur.execute(q("DELETE FROM login_failures WHERE email = %s AND COALESCE(client, '') = %s"), (email, client))
            cur.execute(q("UPDATE users SET last_login_at = NOW() WHERE id = %s"), (row[0],))
            cur.execute(q("INSERT INTO sign_ins (user_id) VALUES (%s)"), (row[0],))
            user = load_access(cur, {
                "id": row[0],
                "email": row[1],
                "full_name": row[3],
                "account_type": row[4],
                "company_id": row[5],
                "company_name": row[6],
                "sector": row[7],
            })
        conn.commit()
    if user["account_type"] == "founder" and not (user["company_id"] and "portal.use" in user["permissions"]):
        raise HTTPException(status_code=403, detail="This founder account is not linked to a company yet. Contact Demo Ventures.")
    if user["account_type"] == "staff" and not user["roles"]:
        raise HTTPException(status_code=403, detail="Your account has no role yet. Ask a Super Admin to assign one.")
    token = create_session(user["id"])
    return {"token": token, "user": user, "redirect": _login_redirect(user)}


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(auth_session)) -> dict[str, Any]:
    return {"user": user}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


@app.post("/api/auth/change-password")
def change_password(
    body: PasswordChange, authorization: str | None = Header(default=None), user: dict = Depends(auth_session)
) -> dict[str, str]:
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Choose a password different from the current one")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT password_hash FROM users WHERE id = %s"), (user["id"],))
            row = cur.fetchone()
            if not row or not bcrypt.checkpw(body.current_password.encode(), row[0].encode()):
                raise HTTPException(status_code=403, detail="Current password is incorrect")
            new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
            cur.execute(q("UPDATE users SET password_hash = %s WHERE id = %s"), (new_hash, user["id"]))
            # Sign out every other device; keep the session making this request.
            current = (authorization or "").removeprefix("Bearer ").strip()
            cur.execute(q("DELETE FROM user_sessions WHERE user_id = %s AND token <> %s"), (user["id"], current))
        conn.commit()
    return {"status": "password_changed"}


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if authorization and authorization.startswith("Bearer "):
        revoke_session(authorization.removeprefix("Bearer ").strip())
    return {"status": "logged_out"}


# A resource is for one company, or portfolio-wide and possibly narrowed by company, sector and stage (audience.py).
VISIBLE_TO_COMPANY = f"{visible()} AND (company_id IS NOT NULL OR is_portfolio_wide) AND status = 'approved'"
# The Resource Library and its counts and suggestions; Playbook guides are offered on the Playbook page instead.
IN_LIBRARY = f"{VISIBLE_TO_COMPANY} AND placement = 'library'"


@app.get("/api/founder/dashboard")
def founder_dashboard(user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder_or_preview(user)
    cid, company_name = founder_company(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            if user.get("account_type") == "staff":
                _audit_once(cur, user, "preview.open", company_name, cid)
            cur.execute(q(f"SELECT COUNT(*) FROM resources WHERE {IN_LIBRARY}"), (cid,))
            resource_count = cur.fetchone()[0]
            cur.execute(q("SELECT COUNT(*) FROM connect_entries WHERE active IS TRUE AND approval = 'approved' AND NOT is_sample"))
            connect_count = cur.fetchone()[0]
            cur.execute(
                q(
                    """
                SELECT COUNT(*) FROM founder_help h JOIN work_items w ON w.help_id = h.id
                WHERE h.company_id = %s AND w.internal_status <> 'resolved'
                """
                ),
                (cid,),
            )
            help_count = cur.fetchone()[0]
            cur.execute(
                q(
                    "SELECT progress_pct, current_phase, owner_name FROM playbook_progress WHERE company_id = %s LIMIT 1"
                ),
                (cid,),
            )
            pb = cur.fetchone()
            cur.execute(
                q(
                    f"""
                SELECT id, label, title, summary FROM sector_updates
                WHERE {visible()} AND approval = 'approved' AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY published_at DESC LIMIT 5
                """
                ),
                (cid,),
            )
            updates = [
                {"id": r[0], "label": r[1], "title": r[2], "summary": r[3]} for r in cur.fetchall()
            ]
            cur.execute(
                q(
                    """
                SELECT id, title FROM resources
                WHERE company_id = %s AND status = 'approved' AND placement = 'library' ORDER BY reviewed_at DESC NULLS LAST LIMIT 1
                """
                ),
                (cid,),
            )
            spotlight = cur.fetchone()
            cur.execute(
                q(
                    f"""
                SELECT e.id, e.title, e.location, e.starts_at, e.company_id, e.is_sample,
                    EXISTS (SELECT 1 FROM event_rsvps r WHERE r.event_id = e.id AND r.user_id = %s)
                FROM events e WHERE e.active AND e.approval = 'approved' AND e.starts_at > NOW() AND {visible('e')}
                ORDER BY e.starts_at LIMIT 1
                """
                ),
                (user["id"], cid),
            )
            ev = cur.fetchone()
            cur.execute(
                q(
                    """
                SELECT COUNT(*) FILTER (WHERE done), COUNT(*) FROM playbook_tasks
                WHERE company_id = %s AND phase_no = (
                    SELECT COALESCE(MIN(phase_no), 4) FROM playbook_tasks WHERE company_id = %s AND NOT done)
                """
                ),
                (cid, cid),
            )
            phase_tasks = cur.fetchone()
        conn.commit()  # keeps the preview audit entry
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT logo_data FROM companies WHERE id = %s"), (cid,))
            logo_row = cur.fetchone()
    return {
        "company_name": company_name,
        "company_logo": (logo_row[0] if logo_row else None) or "",
        "founder_name": user["full_name"],
        "metrics": {
            "resources": resource_count,
            "connections": connect_count,
            "open_help": help_count,
            "playbook_pct": pb[0] if pb else 0,
            "playbook_phase": pb[1] if pb else "",
            "playbook_owner": pb[2] if pb else "",
        },
        "sector_updates": updates,
        "company_resource": {"id": spotlight[0], "title": spotlight[1]} if spotlight else None,
        "next_event": {
            "id": ev[0], "title": ev[1], "location": ev[2], "starts_at": _iso(ev[3]),
            "audience": "Invited for your company" if ev[4] else "Portfolio-wide", "is_sample": ev[5], "going": ev[6],
        } if ev else None,
        "phase_tasks": {"done": phase_tasks[0], "total": phase_tasks[1]},
    }


@app.get("/api/founder/resources")
def founder_resources(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    require_founder_or_preview(user)
    cid = effective_company_id(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    f"""
                SELECT id, category, subcategory, title, description, resource_type, review_note,
                       content_owner, reviewed_at, file_name, tags, company_id
                FROM resources
                WHERE {IN_LIBRARY}
                ORDER BY category, title
                """
                ),
                (cid,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "category": r[1],
            "subcategory": r[2],
            "title": r[3],
            "description": r[4],
            "resource_type": r[5],
            "review_note": r[6],
            "content_owner": r[7],
            "reviewed_at": _iso(r[8]),
            "downloadable": _resource_path(r[9]) is not None,
            "tags": r[10] or [],
            "company_specific": r[11] is not None,
        }
        for r in rows
    ]


def _send_resource(row: tuple, user: dict[str, Any], log_company: int | None) -> FileResponse:
    rid, file_name, title = row
    path = _resource_path(file_name)
    if not path:
        raise HTTPException(status_code=404, detail="File not available yet")
    if log_company is not None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    q("INSERT INTO resource_downloads (resource_id, user_id, company_id) VALUES (%s, %s, %s)"),
                    (rid, user["id"], log_company),
                )
            conn.commit()
    safe_title = re.sub(r"[^A-Za-z0-9 _.-]", "", title).strip() or "resource"
    return FileResponse(path, filename=f"{safe_title}{path.suffix}")


@app.get("/api/founder/resources/{resource_id}/download")
def founder_download(resource_id: int, user: dict = Depends(auth_session)) -> FileResponse:
    require_founder_or_preview(user)
    cid = effective_company_id(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(f"SELECT id, file_name, title FROM resources WHERE id = %s AND {VISIBLE_TO_COMPANY}"),
                (resource_id, cid),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Resource not found")
    return _send_resource(row, user, cid if user.get("account_type") == "founder" else None)  # previews are not founder activity


def _recommend(cur, cid: int, answers: dict[str, Any], limit: int = 6) -> list[int]:
    """Round-robin across the founder's priorities so one heavily-tagged area cannot crowd out the rest."""
    priorities = [p for p in (answers.get("priorities") or []) if p in PRIORITY_TO_TAGS]
    if str(answers.get("fundraising", "")).startswith(("Preparing", "Actively")) and "Fundraising" not in priorities:
        priorities.append("Fundraising")
    if not priorities:
        return []
    # id order = catalog order, which lists the core item of each area first.
    cur.execute(q(f"SELECT id, tags, category FROM resources WHERE {IN_LIBRARY} ORDER BY id"), (cid,))
    rows = cur.fetchall()
    ranked: list[list[int]] = []
    for p in priorities:
        wanted = set(PRIORITY_TO_TAGS[p])
        home = PRIORITY_TO_CATEGORY.get(p)
        matches = sorted(
            (
                (len(wanted & set(tags or [])) + (2 if cat == home else 0), rid)
                for rid, tags, cat in rows
                if wanted & set(tags or [])
            ),
            key=lambda x: (-x[0], x[1]),
        )
        ranked.append([rid for _, rid in matches])
    picked: list[int] = []
    for i in range(max(len(r) for r in ranked)):
        for r in ranked:
            if i < len(r) and r[i] not in picked:
                picked.append(r[i])
            if len(picked) == limit:
                return picked
    return picked


@app.post("/api/founder/intake")
def submit_intake(body: IntakeBody, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder(user)
    cid = effective_company_id(user)
    answers = body.model_dump()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q("INSERT INTO founder_intake (company_id, user_id, answers) VALUES (%s, %s, %s) RETURNING created_at"),
                (cid, user["id"], json.dumps(answers)),
            )
            created = cur.fetchone()[0]
            recommended = _recommend(cur, cid, answers)
        conn.commit()
    return {"answers": answers, "created_at": _iso(created), "recommended_ids": recommended}


@app.get("/api/founder/intake")
def latest_intake(user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder_or_preview(user)
    cid = effective_company_id(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q("SELECT answers, created_at FROM founder_intake WHERE company_id = %s ORDER BY created_at DESC LIMIT 1"),
                (cid,),
            )
            row = cur.fetchone()
            if not row:
                return {"answers": None, "recommended_ids": []}
            answers = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            recommended = _recommend(cur, cid, answers)
    return {"answers": answers, "created_at": _iso(row[1]), "recommended_ids": recommended}


@app.get("/api/founder/activity")
def founder_activity(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    require_founder_or_preview(user)
    cid = effective_company_id(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    """
                SELECT * FROM (
                    SELECT 'download' AS kind, r.title AS title, r.category AS detail, d.created_at AS at
                    FROM resource_downloads d JOIN resources r ON r.id = d.resource_id WHERE d.company_id = %s
                    UNION ALL
                    SELECT 'help', h.subject, h.founder_status, h.updated_at FROM founder_help h WHERE h.company_id = %s
                    UNION ALL
                    SELECT 'intake', 'Company profile updated', 'Resource Library personalised', i.created_at
                    FROM founder_intake i WHERE i.company_id = %s
                    UNION ALL
                    SELECT 'task', t.title, 'Playbook task completed by ' || COALESCE(t.done_by, 'your team'), t.done_at
                    FROM playbook_tasks t WHERE t.company_id = %s AND t.done AND t.done_at IS NOT NULL
                    UNION ALL
                    SELECT 'rsvp', e.title, 'RSVP confirmed', r.created_at
                    FROM event_rsvps r JOIN events e ON e.id = r.event_id JOIN users u ON u.id = r.user_id
                    WHERE u.company_id = %s
                ) a ORDER BY at DESC LIMIT 8
                """
                ),
                (cid, cid, cid, cid, cid),
            )
            rows = cur.fetchall()
    return [{"kind": r[0], "title": r[1], "detail": r[2], "at": _iso(r[3])} for r in rows]


@app.post("/api/founder/help")
def create_help(body: HelpBody, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder(user)
    public_ref = f"YN-{uuid.uuid4().hex[:6].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        with conn.cursor() as cur:
            if body.connect_entry_id is not None:
                cur.execute(q("SELECT 1 FROM connect_entries WHERE id = %s AND active AND approval = 'approved'"), (body.connect_entry_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=422, detail="Unknown Connect profile")
            if body.resource_id is not None:
                cur.execute(
                    q(f"SELECT 1 FROM resources WHERE id = %s AND {VISIBLE_TO_COMPANY}"),
                    (body.resource_id, effective_company_id(user)),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=422, detail="Unknown resource")
            cur.execute(
                q(
                    """
                INSERT INTO founder_help
                (public_ref, company_id, user_id, subject, context, category, resource_id, connect_entry_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """
                ),
                (
                    public_ref,
                    effective_company_id(user),
                    user["id"],
                    body.subject,
                    body.context,
                    body.category,
                    body.resource_id,
                    body.connect_entry_id,
                    now,
                ),
            )
            help_id = cur.fetchone()[0]
            cur.execute(
                q(
                    """
                INSERT INTO work_items (help_id, internal_status, priority)
                VALUES (%s, 'queued', 'normal')
                """
                ),
                (help_id,),
            )
            cid = effective_company_id(user)
            alert_ids = notify(
                cur, company_team(cur, cid), f"New founder request {public_ref}: {body.subject}"[:200],
                f"{user['full_name']} ({user.get('company_name') or 'their company'}) sent a request"
                f"{f' about {body.category}' if body.category else ''}:\n\n{body.subject}\n{(body.context or '').strip()}\n\n"
                f"Open it in Founder requests: {workspace_link('queue')}",
                "request", user["full_name"], cid)
        conn.commit()
    deliver_later(alert_ids)
    return {
        "public_ref": public_ref,
        "founder_status": "Demo Ventures is reviewing your request",
        "message": "Thank you, your Demo Ventures team has received this.",
    }


@app.get("/api/founder/help")
def list_help(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    require_founder_or_preview(user)
    cid = effective_company_id(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    """
                SELECT h.public_ref, h.subject, h.founder_status, h.created_at, h.context, h.category,
                       COALESCE(r.title, ce.display_name), w.assigned_to, w.internal_status,
                       (SELECT COUNT(*) FROM help_messages m WHERE m.help_id = h.id)
                FROM founder_help h
                LEFT JOIN resources r ON r.id = h.resource_id
                LEFT JOIN connect_entries ce ON ce.id = h.connect_entry_id
                LEFT JOIN work_items w ON w.help_id = h.id
                WHERE h.company_id = %s ORDER BY h.created_at DESC
                """
                ),
                (cid,),
            )
            rows = cur.fetchall()
    return [
        {
            "public_ref": r[0],
            "subject": r[1],
            "status": r[2],
            "created_at": _iso(r[3]),
            "context": r[4],
            "category": r[5],
            "resource_title": r[6],
            "owner": r[7] or "Demo Ventures team",
            "resolved": r[8] == "resolved",
            "messages": r[9],
        }
        for r in rows
    ]


class WorkItemPatch(BaseModel):
    internal_status: str | None = None
    assigned_to: str | None = Field(default=None, max_length=120)
    priority: str | None = None


WORK_STATUSES = ("queued", "assigned", "in_progress", "resolved")
PRIORITIES = ("low", "normal", "high")


@app.patch("/api/analyst/work-items/{work_item_id}")
def patch_work_item(
    work_item_id: int, body: WorkItemPatch, user: dict = Depends(auth_session)
) -> dict[str, str]:
    require_perm(user, "requests.handle")
    if body.internal_status is not None and body.internal_status not in WORK_STATUSES:
        raise HTTPException(status_code=422, detail=f"internal_status must be one of {WORK_STATUSES}")
    if body.priority is not None and body.priority not in PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {PRIORITIES}")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q("SELECT h.public_ref, h.company_id FROM work_items w JOIN founder_help h ON h.id = w.help_id WHERE w.id = %s"),
                (work_item_id,),
            )
            item = cur.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="Work item not found")
            allowed = company_scope(user, "requests.handle")
            if allowed is not None and item[1] not in allowed:
                raise HTTPException(status_code=403, detail="You are not assigned to this company")
            if body.assigned_to is not None:
                body.assigned_to = check_staff_name(cur, body.assigned_to) or ""
            _audit(cur, user, "request.update", item[0], body.model_dump(exclude_none=True), item[1])
            if body.internal_status is not None:
                cur.execute(
                    q("UPDATE work_items SET internal_status = %s, updated_at = NOW() WHERE id = %s"),
                    (body.internal_status, work_item_id),
                )
                cur.execute(
                    q(
                        """
                    UPDATE founder_help SET founder_status = %s, updated_at = NOW()
                    WHERE id = (SELECT help_id FROM work_items WHERE id = %s)
                    """
                    ),
                    (_founder_status(body.internal_status), work_item_id),
                )
            if body.assigned_to is not None:
                cur.execute(
                    q("UPDATE work_items SET assigned_to = %s, updated_at = NOW() WHERE id = %s"),
                    (body.assigned_to or None, work_item_id),
                )
            if body.priority is not None:
                cur.execute(
                    q("UPDATE work_items SET priority = %s, updated_at = NOW() WHERE id = %s"),
                    (body.priority, work_item_id),
                )
        conn.commit()
    return {"status": "updated"}


def _founder_status(internal: str | None) -> str:
    if not internal:
        return "Demo Ventures is reviewing your request"
    mapping = {
        "queued": "Demo Ventures is reviewing your request",
        "assigned": "Demo Ventures team member is looking into this",
        "in_progress": "Demo Ventures is working on this",
        "resolved": "Demo Ventures has completed this request",
    }
    return mapping.get(internal, "Demo Ventures is reviewing your request")


@app.get("/api/founder/sector-updates")
def founder_sector_updates(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    require_founder_or_preview(user)
    cid = effective_company_id(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    f"""
                SELECT id, label, title, summary, sector, source, published_at, expires_at, source_url, why
                FROM sector_updates WHERE {visible()} AND approval = 'approved' AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY published_at DESC
                """
                ),
                (cid,),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "label": r[1],
            "title": r[2],
            "summary": r[3],
            "sector": r[4],
            "source": r[5],
            "published_at": _iso(r[6]),
            "expires_at": _iso(r[7]),
            "source_url": r[8] if (r[8] or "").startswith(("https://", "http://")) else None,
            "why": r[9],
        }
        for r in rows
    ]


@app.get("/api/analyst/work-items")
def analyst_queue(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    """Founder requests: the Super Admin sees all; Admins and Analysts see their own companies'."""
    require_perm(user, "requests.handle")
    allowed = company_scope(user, "requests.handle")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    """
                SELECT w.id, h.public_ref, h.subject, h.context, h.category,
                       w.internal_status, w.priority, w.assigned_to, c.name, h.created_at, r.title, u.full_name,
                       (SELECT a.person FROM company_assignments a WHERE a.company_id = c.id AND a.role = 'portfolio_analyst'
                        ORDER BY a.effective_from DESC, a.id DESC LIMIT 1),
                       h.connect_entry_id IS NOT NULL,
                       (SELECT COUNT(*) FROM help_messages m WHERE m.help_id = h.id),
                       (SELECT m.from_fund FROM help_messages m WHERE m.help_id = h.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1),
                       h.company_id
                FROM work_items w
                JOIN founder_help h ON h.id = w.help_id
                JOIN companies c ON c.id = h.company_id
                JOIN users u ON u.id = h.user_id
                LEFT JOIN resources r ON r.id = h.resource_id
                WHERE (%s::int[] IS NULL OR h.company_id = ANY(%s::int[]))
                ORDER BY (w.internal_status = 'resolved'), w.created_at DESC
                LIMIT 200
                """
                ),
                (list(allowed) if allowed is not None else None,) * 2,
            )
            rows = cur.fetchall()
    return [
        {
            "work_item_id": r[0],
            "public_ref": r[1],
            "subject": r[2],
            "context": r[3],
            "category": r[4],
            "internal_status": r[5],
            "priority": r[6],
            "assigned_to": r[7],
            "company_name": r[8],
            "created_at": _iso(r[9]),
            "resource_title": r[10],
            "founder_name": r[11],
            "suggested_owner": r[12],
            "introduction": r[13],
            "messages": r[14],
            "awaiting_reply": r[15] is False,  # the founder wrote last
        }
        for r, cid in ((row[:-1], row[-1]) for row in rows)
        if allowed is None or cid in allowed
    ]


# ---------------------------------------------------------------- content governance
def _next_review_monday() -> str:
    today = datetime.now(timezone.utc).date()
    days = (0 - today.weekday()) % 7
    return (today + timedelta(days=days)).isoformat()


@app.get("/api/analyst/resources")
def analyst_resources(status: str | None = None, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_perm(user, "content.submit", "content.approve")
    if status and status not in RESOURCE_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {RESOURCE_STATUSES}")
    sql = """
        SELECT r.id, r.category, r.subcategory, r.title, r.description, r.resource_type, r.status,
               r.content_owner, r.submitted_by, r.reviewed_by, r.reviewed_at, r.review_comment,
               r.file_name, r.source_url, r.updated_at, c.name,
               (SELECT COUNT(*) FROM resource_downloads d WHERE d.resource_id = r.id), r.tags,
               (r.pending_changes IS NOT NULL OR r.pending_file IS NOT NULL), r.pending_by,
               r.company_id, r.target_company_ids, r.target_sectors, r.target_stages, r.placement
        FROM resources r LEFT JOIN companies c ON c.id = r.company_id
    """
    allowed = company_scope(user, "companies.view")
    ids = list(allowed) if allowed is not None else None
    sql += " WHERE (%s::int[] IS NULL OR r.company_id IS NULL OR r.company_id = ANY(%s::int[]))"
    params: tuple = (ids, ids)
    if status:
        sql += " AND r.status = %s"
        params = (ids, ids, status)
    sql += " ORDER BY (r.status <> 'in_review'), r.updated_at DESC"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q(sql), params)
            rows = cur.fetchall()
            cur.execute(q("SELECT status, COUNT(*) FROM resources GROUP BY status"))
            counts = dict(cur.fetchall())
            cur.execute(q("SELECT id, name FROM companies"))
            names = dict(cur.fetchall())
    return {
        "next_review": _next_review_monday(),
        "counts": counts,
        "items": [
            {
                "id": r[0],
                "category": r[1],
                "subcategory": r[2],
                "title": r[3],
                "description": r[4],
                "resource_type": r[5],
                "status": r[6],
                "content_owner": r[7],
                "submitted_by": r[8],
                "reviewed_by": r[9],
                "reviewed_at": _iso(r[10]),
                "review_comment": r[11],
                "has_file": _resource_path(r[12]) is not None,
                "source_url": r[13],
                "tags": list(r[17] or []),
                "updated_at": _iso(r[14]),
                "visibility": describe(r[15], r[21], r[22], r[23], names),
                "company_id": r[20],
                "target_company_ids": list(r[21] or []),
                "target_sectors": list(r[22] or []),
                "target_stages": list(r[23] or []),
                "downloads": r[16],
                "edit_waiting": r[18],
                "edit_by": r[19],
                "placement": r[24],
            }
            for r in rows
        ],
    }


async def _store_upload(file: UploadFile) -> tuple[str, str]:
    """Validate and save an uploaded resource file under CONTENT_DIR/uploads. Returns (stored name, extension)."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=422, detail=f"File type must be one of {sorted(ALLOWED_UPLOAD_EXT)}")
    data = await file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File larger than {MAX_UPLOAD_MB} MB")
    if not data:
        raise HTTPException(status_code=422, detail="File is empty")
    uploads = UPLOAD_DIR
    uploads.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (uploads / stored).write_bytes(data)
    return stored, ext


@app.post("/api/analyst/resources")
async def submit_resource(
    title: str = Form(..., min_length=3, max_length=160),
    category: str = Form(..., min_length=2, max_length=60),
    description: str = Form(..., min_length=10, max_length=600),
    subcategory: str | None = Form(default=None, max_length=60),
    content_owner: str | None = Form(default=None, max_length=80),
    source_url: str | None = Form(default=None, max_length=500),
    tags: str | None = Form(default=None, max_length=200),
    audience: str | None = Form(default=None, max_length=4000),  # JSON: {"company_id": .., "target_sectors": [..], ..}
    file: UploadFile = File(...),
    user: dict = Depends(auth_session),
) -> dict[str, Any]:
    """Upload a resource for the weekly review. It is never visible to founders until approved."""
    require_perm(user, "content.submit")
    if source_url and not source_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Source URL must start with http(s)://")
    aud_in = _parse_audience(audience)
    with get_conn() as conn:
        with conn.cursor() as cur:
            aud = _resource_audience(cur, user, aud_in)  # checked before the file is stored
    stored, ext = await _store_upload(file)
    tag_list = [t.strip().lower() for t in (tags or "").split(",") if t.strip()][:10]
    slug = f"upload-{stored[:12]}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    """
                INSERT INTO resources (slug, category, subcategory, title, description, resource_type, review_note,
                    is_portfolio_wide, status, file_name, content_owner, tags, submitted_by, source_url,
                    company_id, target_company_ids, target_sectors, target_stages)
                VALUES (%s, %s, %s, %s, %s, %s, 'Awaiting Monday content review', %s, 'in_review', %s, %s, %s, %s, %s,
                    %s, %s, %s, %s)
                RETURNING id
                """
                ),
                (slug, category, subcategory, title, description, ext.lstrip(".").upper(), aud["is_portfolio_wide"], stored,
                 content_owner, tag_list, user["full_name"], source_url, aud["company_id"], aud["target_company_ids"],
                 aud["target_sectors"], aud["target_stages"]),
            )
            rid = cur.fetchone()[0]
            _audit(cur, user, "resource.submit", title, {"category": category})
        conn.commit()
    return {"id": rid, "status": "in_review", "next_review": _next_review_monday()}


@app.patch("/api/analyst/resources/{resource_id}")
def review_resource(resource_id: int, body: ResourceReview, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_perm(user, "content.approve" if body.action != "resubmit" else "content.submit", "content.approve")
    transitions = {"approve": "approved", "reject": "rejected", "archive": "archived", "resubmit": "in_review"}
    if body.action not in transitions:
        raise HTTPException(status_code=422, detail=f"action must be one of {sorted(transitions)}")
    if body.action == "reject" and not (body.comment or "").strip():
        raise HTTPException(status_code=422, detail="A comment is required when rejecting")
    new_status = transitions[body.action]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT file_name, title, company_id, status FROM resources WHERE id = %s"), (resource_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Resource not found")
            if body.action == "resubmit" and not has_perm(user, "content.approve") and row[3] != "rejected":
                raise HTTPException(status_code=422, detail="Only a returned resource can be sent back to review")
            _audit(cur, user, f"resource.{body.action}", row[1], {"comment": body.comment} if body.comment else None, row[2])
            if new_status == "approved" and not _resource_path(row[0]):
                raise HTTPException(status_code=422, detail="Cannot approve a resource without a file")
            note = {
                "approved": "Approved by Demo Ventures at content review",
                "rejected": "Returned to content owner",
                "archived": "Withdrawn from the library",
                "in_review": "Awaiting Monday content review",
            }[new_status]
            cur.execute(
                q(
                    """
                UPDATE resources SET status = %s, reviewed_by = %s, reviewed_at = NOW(), review_comment = %s,
                    review_note = %s, updated_at = NOW()
                WHERE id = %s
                """
                ),
                (new_status, user["full_name"], body.comment, note, resource_id),
            )
        conn.commit()
    return {"id": resource_id, "status": new_status}


def _resource_audience(cur, user: dict[str, Any], aud: Audience) -> dict[str, Any]:
    """Columns for a resource's audience: one company, or portfolio-wide narrowed by companies, sectors, stages."""
    a = clean_audience(cur, aud, company_scope(user, "companies.view"))
    return {"company_id": a["company_id"], "is_portfolio_wide": a["company_id"] is None,
            "target_company_ids": a["target_company_ids"], "target_sectors": a["target_sectors"],
            "target_stages": a["target_stages"]}


def _parse_audience(text: str | None) -> Audience:
    if not text:
        return Audience()
    try:
        return Audience.model_validate_json(text)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Audience is not valid") from e


class ResourceEdit(BaseModel):
    audience: Audience | None = None  # who the resource is for (one company, or portfolio-wide narrowed by targets)
    title: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, min_length=10, max_length=600)
    category: str | None = Field(default=None, min_length=2, max_length=60)
    subcategory: str | None = Field(default=None, max_length=60)
    content_owner: str | None = Field(default=None, max_length=80)
    source_url: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=10)


def _after_edit(cur, resource_id: int, user: dict[str, Any], what: str) -> str:
    """A published resource edited by someone who cannot approve goes back to review, so founders never
    see unreviewed changes. The Super Admin's own edits stay published. Returns the new status."""
    cur.execute(q("SELECT status, title, company_id FROM resources WHERE id = %s"), (resource_id,))
    status, title, company_id = cur.fetchone()
    if status == "approved" and not has_perm(user, "content.approve"):
        status = "in_review"
        cur.execute(
            q("UPDATE resources SET status = 'in_review', review_note = %s, updated_at = NOW() WHERE id = %s"),
            (f"{what} by {user['full_name']}; awaiting review", resource_id),
        )
    else:
        cur.execute(q("UPDATE resources SET updated_at = NOW() WHERE id = %s"), (resource_id,))
    _audit(cur, user, "resource.edit", title, {"change": what, "status": status}, company_id)
    return status


@app.patch("/api/analyst/resources/{resource_id}/details")
def edit_resource(resource_id: int, body: ResourceEdit, user: dict = Depends(auth_session)) -> dict[str, Any]:
    """Edit a resource's title, description, category and other details."""
    require_perm(user, "content.submit", "content.approve")
    changes = body.model_dump(exclude_none=True, exclude={"audience"})
    if not changes and body.audience is None:
        raise HTTPException(status_code=422, detail="Nothing to update")
    if changes.get("source_url") and not changes["source_url"].startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Source URL must start with http(s)://")
    if "tags" in changes:
        changes["tags"] = [t.strip().lower() for t in changes["tags"] if t.strip()][:10]
    with get_conn() as conn:
        with conn.cursor() as cur:
            if body.audience is not None:
                changes.update(_resource_audience(cur, user, body.audience))
            cur.execute(q("SELECT status, pending_changes, title, company_id FROM resources WHERE id = %s"), (resource_id,))
            found = cur.fetchone()
            if not found:
                raise HTTPException(status_code=404, detail="Resource not found")
            if found[0] == "approved" and not has_perm(user, "content.approve"):
                pending = {**json.loads(found[1] or "{}"), **changes}
                cur.execute(
                    q("UPDATE resources SET pending_changes = %s, pending_by = %s, pending_at = NOW() WHERE id = %s"),
                    (json.dumps(pending), user["full_name"], resource_id),
                )
                _audit(cur, user, "resource.edit", found[2], {"change": "Details edited", "waits_for_approval": True}, found[3])
                conn.commit()
                return {"id": resource_id, "status": "approved", "pending": True}
            for col, val in changes.items():  # column names come from the pydantic model / _resource_audience
                keep = isinstance(val, (list, bool, int))
                cur.execute(q(f"UPDATE resources SET {col} = %s WHERE id = %s"), (val if keep else (val or None), resource_id))
            status = _after_edit(cur, resource_id, user, "Details edited")
        conn.commit()
    return {"id": resource_id, "status": status}


@app.post("/api/analyst/resources/{resource_id}/file")
async def replace_resource_file(resource_id: int, file: UploadFile = File(...), user: dict = Depends(auth_session)) -> dict[str, Any]:
    """Replace a resource's file with a new version (same checks as an upload)."""
    require_perm(user, "content.submit", "content.approve")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT file_name FROM resources WHERE id = %s"), (resource_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Resource not found")
    stored, ext = await _store_upload(file)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT status, title, company_id, pending_file FROM resources WHERE id = %s"), (resource_id,))
            status, title, company_id, old_pending = cur.fetchone()
            if status == "approved" and not has_perm(user, "content.approve"):
                # The published file stays live; the new one waits for the Super Admin.
                cur.execute(
                    q("UPDATE resources SET pending_file = %s, pending_by = %s, pending_at = NOW() WHERE id = %s"),
                    (stored, user["full_name"], resource_id),
                )
                _audit(cur, user, "resource.edit", title, {"change": "File replaced", "waits_for_approval": True}, company_id)
                conn.commit()
                stale = _resource_path(old_pending) if old_pending else None
                if stale and UPLOAD_DIR.resolve() in stale.parents:
                    stale.unlink(missing_ok=True)
                return {"id": resource_id, "status": "approved", "pending": True, "file_type": ext.lstrip(".").upper()}
            cur.execute(
                q("UPDATE resources SET file_name = %s, resource_type = %s WHERE id = %s"),
                (stored, ext.lstrip(".").upper(), resource_id),
            )
            status = _after_edit(cur, resource_id, user, "File replaced")
        conn.commit()
    old = _resource_path(row[0])
    uploads = UPLOAD_DIR.resolve()
    if old and uploads in old.parents:  # earlier uploads are removed; the curated alpha files are kept
        old.unlink(missing_ok=True)
    return {"id": resource_id, "status": status, "file_type": ext.lstrip(".").upper()}


@app.get("/api/analyst/resources/{resource_id}/download")
def analyst_download(resource_id: int, user: dict = Depends(auth_session)) -> FileResponse:
    """Preview any resource (including drafts) for review. Not logged as founder activity."""
    require_perm(user, "content.submit", "content.approve")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT id, file_name, title, company_id FROM resources WHERE id = %s"), (resource_id,))
            found = cur.fetchone()
            if found and found[3] is not None:
                allowed = company_scope(user, "companies.view")
                if allowed is not None and found[3] not in allowed:
                    raise HTTPException(status_code=403, detail="You are not assigned to this company")
            row = found[:3] if found else None
    if not row:
        raise HTTPException(status_code=404, detail="Resource not found")
    return _send_resource(row, user, None)


def _audit_once(cur, user: dict[str, Any], action: str, target: str, company_id: int | None, minutes: int = 30) -> None:
    """Record a read (a founder-portal preview, questionnaire answers) at most once per half hour."""
    cur.execute(
        q("SELECT 1 FROM admin_audit WHERE actor = %s AND action = %s AND COALESCE(company_id, 0) = COALESCE(%s, 0) "
          "AND created_at > NOW() - make_interval(mins => %s)"),
        (user["email"], action, company_id, minutes),
    )
    if not cur.fetchone():
        _audit(cur, user, action, target, None, company_id)


@app.get("/api/analyst/intakes")
def analyst_intakes(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    require_perm(user, "intakes.view")
    allowed = company_scope(user, "intakes.view")
    ids = list(allowed) if allowed is not None else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    """
                SELECT i.id, c.name, u.full_name, i.answers, i.created_at, i.company_id
                FROM founder_intake i JOIN companies c ON c.id = i.company_id JOIN users u ON u.id = i.user_id
                WHERE (%s::int[] IS NULL OR i.company_id = ANY(%s::int[]))
                ORDER BY i.created_at DESC LIMIT 100
                """
                ),
                (ids, ids),
            )
            rows = cur.fetchall()
            for cname, cid in {(r[1], r[5]) for r in rows}:  # who read which company's answers
                _audit_once(cur, user, "intakes.view", cname, cid)
        conn.commit()
    return [
        {
            "id": r[0],
            "company_name": r[1],
            "founder_name": r[2],
            "answers": r[3] if isinstance(r[3], dict) else json.loads(r[3]),
            "created_at": _iso(r[4]),
        }
        for r in rows
    ]


RESOURCE_CSV_COLUMNS = ["title", "category", "subcategory", "description", "content_owner", "source_url", "tags", "file_name"]
# Optional audience columns: for_company (a company short ID), sectors and stages (separated by ";").
RESOURCE_CSV_AUDIENCE = ("for_company", "sectors", "stages")
RESOURCE_CATEGORIES = ("Finance and Compliance", "Fundraising and Investor Relations", "Growth & Sales", "Business Operations", "Product & Tech Strategy", "Market Intelligence", "People & Hiring", "Research and Reports")


@app.get("/api/analyst/resources/bulk-template")
def resources_template(user: dict = Depends(auth_session)) -> Response:
    require_perm(user, "content.submit")
    import csv
    import io

    buf = io.StringIO()
    csv.writer(buf).writerows([
        [*RESOURCE_CSV_COLUMNS, *RESOURCE_CSV_AUDIENCE],
        ["Board Meeting Agenda Template", "Business Operations", "Governance", "A one-page agenda for monthly board meetings.",
         "Sara", "", "board; governance", "board-agenda.docx", "", "", "Seed; Series A"],
    ])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="resources-template.csv"'})


def _csv_audience(r: dict[str, str], user: dict[str, Any]) -> dict[str, Any]:
    """Audience from the optional CSV columns: for_company (short ID), sectors and stages (";"-separated)."""
    split = lambda v: [x.strip() for x in re.split(r"[;|]", v or "") if x.strip()]  # noqa: E731
    with get_conn() as conn:
        with conn.cursor() as cur:
            cid = None
            if r.get("for_company"):
                cur.execute(q("SELECT id FROM companies WHERE slug = %s"), (r["for_company"].strip().lower(),))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=422, detail=f"for_company: no company with short ID {r['for_company']}")
                cid = row[0]
            return _resource_audience(cur, user, Audience(company_id=cid, target_sectors=split(r.get("sectors")),
                                                          target_stages=split(r.get("stages"))))


@app.post("/api/analyst/resources/bulk")
async def resources_bulk(
    sheet: UploadFile = File(...),
    files: list[UploadFile] = File(default=[]),
    dry_run: bool = Form(True),
    user: dict = Depends(auth_session),
) -> dict[str, Any]:
    """Add many resources at once: one CSV row per resource, plus the files it names. Every new
    resource waits in Content review for the Super Admin. dry_run=true checks and saves nothing."""
    require_perm(user, "content.submit")
    rows = read_csv_upload(await sheet.read(1_000_001), RESOURCE_CSV_COLUMNS, RESOURCE_CSV_AUDIENCE)
    attached: dict[str, bytes] = {}
    for f in files:
        data = await f.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} is larger than {MAX_UPLOAD_MB} MB")
        attached[(f.filename or "").strip().lower()] = data
    checked = []
    for n, r in enumerate(rows, start=2):
        errors = []
        title, cat, desc, fname = r.get("title", ""), r.get("category", ""), r.get("description", ""), r.get("file_name", "")
        if not 3 <= len(title) <= 160:
            errors.append("title must be 3–160 characters")
        if cat not in RESOURCE_CATEGORIES:
            errors.append("category must be one of: " + ", ".join(RESOURCE_CATEGORIES))
        if not 10 <= len(desc) <= 600:
            errors.append("description must be 10–600 characters")
        if r.get("source_url") and not r["source_url"].startswith(("https://", "http://")):
            errors.append("source_url must start with https://")
        if Path(fname).suffix.lower() not in ALLOWED_UPLOAD_EXT:
            errors.append(f"file_name must end in one of {', '.join(sorted(ALLOWED_UPLOAD_EXT))}")
        elif fname.lower() not in attached:
            errors.append(f"file {fname} was not attached")
        elif not attached[fname.lower()]:
            errors.append(f"file {fname} is empty")
        try:
            r["_audience"] = _csv_audience(r, user)
        except HTTPException as e:
            errors.append(str(e.detail))
        checked.append({"row": n, "title": title, "file_name": fname, "errors": errors})
    ok = not any(c["errors"] for c in checked)
    if dry_run or not ok:
        return {"saved": 0, "ok": ok, "rows": checked}
    uploads = UPLOAD_DIR
    uploads.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                ext = Path(r["file_name"]).suffix.lower()
                stored = f"{uuid.uuid4().hex}{ext}"
                (uploads / stored).write_bytes(attached[r["file_name"].lower()])
                tags = [t.strip().lower() for t in re.split(r"[;,]", r.get("tags", "")) if t.strip()][:10]
                cur.execute(
                    q(
                        """
                    INSERT INTO resources (slug, category, subcategory, title, description, resource_type, review_note,
                        is_portfolio_wide, status, file_name, content_owner, tags, submitted_by, source_url,
                        company_id, target_company_ids, target_sectors, target_stages)
                    VALUES (%s, %s, %s, %s, %s, %s, 'Awaiting approval (bulk upload)', %s, 'in_review', %s, %s, %s, %s, %s,
                        %s, %s, %s, %s)
                    """
                    ),
                    (f"upload-{stored[:12]}", r["category"], r.get("subcategory") or None, r["title"], r["description"],
                     ext.lstrip(".").upper(), r["_audience"]["is_portfolio_wide"], stored, r.get("content_owner") or None,
                     tags, user["full_name"], r.get("source_url") or None, r["_audience"]["company_id"],
                     r["_audience"]["target_company_ids"], r["_audience"]["target_sectors"], r["_audience"]["target_stages"]),
                )
            _audit(cur, user, "resource.bulk", f"{len(rows)} resources")
        conn.commit()
    return {"saved": len(rows), "ok": True, "rows": checked}


@app.get("/api/auth/profile")
def my_profile(user: dict = Depends(auth_session)) -> dict[str, Any]:
    """The signed-in person's profile and journey, for founders and every staff tier."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("SELECT created_at, last_login_at FROM users WHERE id = %s"), (user["id"],))
            created, last = cur.fetchone()
            cur.execute(q("SELECT COUNT(*) FROM sign_ins WHERE user_id = %s AND created_at > NOW() - INTERVAL '30 days'"), (user["id"],))
            sign_ins = cur.fetchone()[0]
            tiers = [ROLES[r][0] for r in user.get("roles", []) if r in ROLES]
            profile: dict[str, Any] = {
                "full_name": user["full_name"], "email": user["email"], "account_type": user["account_type"],
                "tier": ", ".join(tiers), "member_since": _iso(created), "last_sign_in": _iso(last), "sign_ins_30d": sign_ins,
                "can_do": [PERMISSIONS[p][0] for p in user.get("permissions", []) if p in PERMISSIONS],
                "recent": person_timeline(cur, user["id"], limit=12),
            }
            cur.execute(
                q(
                    """
                SELECT c.name, a.role, a.person FROM (SELECT DISTINCT ON (company_id, role) company_id, role, person, user_id
                    FROM company_assignments ORDER BY company_id, role, effective_from DESC, id DESC) a
                JOIN companies c ON c.id = a.company_id
                WHERE a.user_id = %s OR a.company_id = %s ORDER BY c.name, a.role
                """
                ),
                (user["id"], user.get("company_id") or -1),
            )
            assignments = cur.fetchall()
            if user["account_type"] == "staff":
                profile["companies"] = sorted({a[0] for a in assignments})
                return profile
            cid = user["company_id"]
            cur.execute(q("SELECT name, sector, stage, city, fund, invested, website, about FROM companies WHERE id = %s"), (cid,))
            name, sector, stage, city, fund, invested, website, about = cur.fetchone()
            profile["company"] = {"name": name, "sector": sector, "stage": stage, "city": city, "fund": fund,
                                  "invested": invested, "website": website, "about": about}
            profile["team"] = {("relationship_manager" if a[1] == "relationship_partner" else "analyst"): a[2] for a in assignments}
            cur.execute(q("SELECT created_at FROM founder_intake WHERE user_id = %s ORDER BY created_at DESC LIMIT 1"), (user["id"],))
            intake = cur.fetchone()
            cur.execute(q("SELECT COUNT(*) FROM resource_downloads WHERE user_id = %s"), (user["id"],))
            downloads = cur.fetchone()[0]
            cur.execute(
                q("SELECT COUNT(*), COUNT(*) FILTER (WHERE founder_status <> 'Demo Ventures has completed this request') FROM founder_help WHERE user_id = %s"),
                (user["id"],),
            )
            requests_total, requests_open = cur.fetchone()
            cur.execute(
                q("SELECT COUNT(*) FROM event_rsvps v JOIN events e ON e.id = v.event_id WHERE v.user_id = %s AND e.starts_at > NOW()"),
                (user["id"],),
            )
            upcoming = cur.fetchone()[0]
            cur.execute(q("SELECT progress_pct, current_phase, owner_name FROM playbook_progress WHERE company_id = %s"), (cid,))
            pb = cur.fetchone()
            cur.execute(q("SELECT COUNT(*) FROM playbook_tasks WHERE company_id = %s AND done AND done_by = %s"), (cid, user["full_name"]))
            ticks = cur.fetchone()[0]
    profile["journey"] = [
        {"step": "Signed in to the portal", "done": True},
        {"step": "Answered the questionnaire", "done": intake is not None},
        {"step": "Downloaded a resource", "done": downloads > 0},
        {"step": "Asked Demo Ventures for help", "done": requests_total > 0},
        {"step": "RSVP'd to an event", "done": upcoming > 0},
        {"step": "Completed a playbook task", "done": ticks > 0},
    ]
    profile["stats"] = {"downloads": downloads, "requests_open": requests_open, "requests_total": requests_total,
                        "upcoming_events": upcoming, "questionnaire_at": _iso(intake[0]) if intake else None}
    profile["playbook"] = {"progress_pct": pb[0], "current_phase": pb[1], "owner": pb[2]} if pb else None
    return profile


app.include_router(admin_router)  # routers must be registered before the /api catch-all below
app.include_router(engagement_router)
app.include_router(news_router)
app.include_router(crm_router)
app.include_router(talent_router)
app.include_router(messages_router)
app.include_router(lms_router)
app.include_router(profile_router)
app.include_router(chat_router)
app.include_router(otp_router)  # sign in with a one-time code; 404 while OTP_SIGNIN_ENABLED is off


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
def api_not_found(path: str) -> None:
    raise HTTPException(status_code=404, detail="Not found")


if not (FRONTEND_DIR / "index.html").is_file():
    raise RuntimeError(f"Frontend build not found at {FRONTEND_DIR}. Run scripts/sync_dist.py first.")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
