"""Admin API, manage the founder portal. Every route checks a permission (backend/permissions.py).

- The portfolio company is the provisioning root; several founders per company.
- Demo Ventures team assignments change over time and keep their history; Admins and Analysts see their
  assigned companies only.
- Everything a non-Super-Admin adds (events, Connect profiles, sector updates; resources live in
  main.py) waits for the Super Admin's approval before founders see it.
- Every admin change is written to admin_audit with its company, so each tier sees the right trail.
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, ValidationError

from backend.audience import STAGES, Audience, clean_audience, company_names, describe, sector_tags, sectors
from backend.db import get_conn
from backend.messaging import (deliver, email_configured, invite_message, link, mailto_url, make_token, outbox_status,
                                queue_email, reset_message, whatsapp_url)
from backend.permissions import PERMISSIONS, ROLES, STAFF_LEVELS, SUPER_ADMIN
from backend.playbook import PHASES, phase_label, seed_template_tasks, sync_progress
from backend.security import colleague_ids, company_scope, has_perm, iso, need, require_company, require_perm

router = APIRouter(prefix="/api/admin")

SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
ASSIGNMENT_ROLES = ("relationship_partner", "portfolio_analyst")
UPDATE_LABELS = ("POLICY", "MARKET", "REGULATORY", "FUNDING", "EVENT")
CONNECT_GROUPS = ("Operational Support Network", "Peer Founder Network", "Investor & Fundraising Ecosystem", "Demo Ventures Network")
IST = timezone(timedelta(hours=5, minutes=30))
MAX_CSV_BYTES = 1_000_000

# Plain-language wording for audit and activity entries (screens never show the codes).
ACTION_LABELS = {
    "company.create": "Added a company", "company.update": "Edited a company",
    "founder.invite": "Invited a founder", "user.rename": "Renamed an account", "user.email": "Changed a founder's email", "user.activate": "Reactivated an account",
    "user.deactivate": "Deactivated an account", "user.reset_password": "Reset a password",
    "team.assign": "Changed the Demo Ventures team", "team.invite": "Added a staff member", "team.level": "Changed a staff tier",
    "super_admin.handover": "Handed over Super Admin",
    "playbook.owner": "Set the playbook owner", "playbook.task_add": "Added a playbook task", "playbook.task_remove": "Removed a playbook task",
    "sector_update.publish": "Added a sector update", "sector_update.withdraw": "Withdrew a sector update",
    "event.create": "Added an event", "event.cancel": "Cancelled an event", "event.restore": "Restored an event",
    "event.recording": "Added a recording link", "event.join_link": "Changed an event's join link", "team.reports_to": "Changed who an analyst reports to",
    "connect.add": "Added a Connect profile", "connect.update": "Edited a Connect profile",
    "connect.hide": "Hid a Connect profile", "connect.show": "Showed a Connect profile", "connect.bulk": "Uploaded Connect profiles (CSV)",
    "approval.approve": "Approved", "approval.return": "Returned for changes",
    "resource.submit": "Uploaded a resource", "resource.bulk": "Uploaded resources (CSV)", "resource.edit": "Edited a resource",
    "resource.approve": "Approved a resource", "resource.reject": "Returned a resource", "resource.archive": "Withdrew a resource",
    "resource.resubmit": "Sent a resource back to review", "resource.download": "Downloaded a resource",
    "request.update": "Updated a founder request", "news_source.add": "Added a news feed", "news_source.update": "Changed a news feed",
    "news.keywords": "Changed news keywords", "auth.sign_in": "Signed in",
    "request.reply": "Replied to a founder request", "company.note": "Added a company note", "company.status": "Changed a company's status",
    "user.unlock": "Cleared a sign-in lock", "company.logo": "Changed a company logo", "user.contact": "Updated contact details", "login.failed": "Failed sign-in",
    "preview.open": "Previewed the founder portal", "intakes.view": "Read questionnaire answers",
    "sector_update.resubmit": "Resubmitted a sector update", "event.resubmit": "Resubmitted an event",
    "profile.update": "Updated a company profile", "profile.confirm": "Confirmed a company profile",
    "profile.import": "Imported a company profile", "firm.rename": "Renamed a firm",
    "tracker.update": "Updated the Demo Ventures tracker", "tracker.import": "Imported the Demo Ventures tracker",
    "playbook.curate": "Curated the Playbook",
}


def action_label(code: str) -> str:
    return ACTION_LABELS.get(code, code.replace("_", " ").replace(".", ": ").capitalize())


def _audit(cur, actor: dict[str, Any], action: str, target: str, details: dict | None = None,
           company_id: int | None = None) -> None:
    cur.execute(
        "INSERT INTO admin_audit (actor, action, target, details, company_id) VALUES (%s, %s, %s, %s, %s)",
        (actor["email"], action, target, json.dumps(details or {}), company_id),
    )


def _temp_password() -> tuple[str, str]:
    temp = secrets.token_urlsafe(9)
    return temp, bcrypt.hashpw(temp.encode(), bcrypt.gensalt()).decode()


def _initial_approval(user: dict[str, Any]) -> str:
    """The Super Admin's own additions go live at once; everyone else's wait for approval."""
    return "approved" if has_perm(user, "content.approve") else "pending"


def _scope_ids(user: dict[str, Any]) -> tuple:
    """(ids, ids) for SQL filters of the form (%s::int[] IS NULL OR company_id = ANY(%s::int[]))."""
    allowed = company_scope(user, "companies.view")
    ids = list(allowed) if allowed is not None else None
    return (ids, ids)


def _in_scope(allowed: set[int] | None, company_id: int | None) -> bool:
    return allowed is None or (company_id is not None and company_id in allowed)


def _may_change(user: dict[str, Any], company_id: int | None, owner: str | None) -> bool:
    """A one-company item: anyone assigned to that company. A portfolio-wide item: the Super Admin or its author."""
    if company_id is not None:
        return _in_scope(company_scope(user, "companies.view"), company_id)
    return has_perm(user, "content.approve") or owner == user["full_name"]




# ---------------------------------------------------------------- audience dropdowns
@router.get("/audience-options")
def audience_options(user: dict = Depends(need("content.submit", "news.publish", "events.manage", "companies.view"))) -> dict[str, Any]:
    """Choices for the audience dropdowns: the companies this person may target, every sector tag, the stages."""
    allowed = company_scope(user, "companies.view")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, sector, stage, status, slug FROM companies ORDER BY name")
            companies = [{"id": r[0], "name": r[1], "sector": r[2], "stage": r[3], "status": r[4], "slug": r[5]}
                         for r in cur.fetchall() if allowed is None or r[0] in allowed]
            tags = sectors(cur)
    return {"companies": companies, "sectors": tags, "stages": STAGES}


# ---------------------------------------------------------------- overview
@router.get("/overview")
def overview(user: dict = Depends(need("overview.view"))) -> dict[str, Any]:
    allowed = company_scope(user, "companies.view")
    with get_conn() as conn:
        with conn.cursor() as cur:
            def one(sql: str, params: tuple = ()) -> int:
                cur.execute(sql, params)
                return cur.fetchone()[0]

            # Company numbers cover the companies this person may see (all of them for the Super Admin).
            ids = list(allowed) if allowed is not None else None
            mine = "(%s::int[] IS NULL OR {col} = ANY(%s::int[]))"
            scope = (ids, ids)
            counts = {
                "companies": one(f"SELECT COUNT(*) FROM companies WHERE {mine.format(col='id')}", scope),
                "active_founders": one(f"SELECT COUNT(*) FROM users WHERE account_type = 'founder' AND active AND {mine.format(col='company_id')}", scope),
                "team_members": one("SELECT COUNT(*) FROM users WHERE account_type = 'staff' AND active"),
                "open_requests": one(f"SELECT COUNT(*) FROM work_items w JOIN founder_help h ON h.id = w.help_id WHERE w.internal_status <> 'resolved' AND {mine.format(col='h.company_id')}", scope),
                "content_in_review": one("SELECT COUNT(*) FROM resources WHERE status = 'in_review'"),
                "approved_resources": one("SELECT COUNT(*) FROM resources WHERE status = 'approved'"),
                "downloads_30d": one(f"SELECT COUNT(*) FROM resource_downloads WHERE created_at > NOW() - INTERVAL '30 days' AND {mine.format(col='company_id')}", scope),
                "intakes_completed": one(f"SELECT COUNT(DISTINCT company_id) FROM founder_intake WHERE {mine.format(col='company_id')}", scope),
                "awaiting_approval": _pending_count(cur),
            }
            cur.execute(
                """
                SELECT r.title, r.category, COUNT(d.id) FROM resources r JOIN resource_downloads d ON d.resource_id = r.id
                WHERE (%s::int[] IS NULL OR d.company_id = ANY(%s::int[]))
                GROUP BY r.id ORDER BY COUNT(d.id) DESC, r.title LIMIT 5
                """, scope
            )
            top = [{"title": t, "category": c, "downloads": n} for t, c, n in cur.fetchall()]
            cur.execute(
                """
                SELECT c.id, c.name,
                    (SELECT COUNT(*) FROM users u WHERE u.company_id = c.id AND u.active),
                    (SELECT COUNT(*) FROM founder_help h JOIN work_items w ON w.help_id = h.id
                        WHERE h.company_id = c.id AND w.internal_status <> 'resolved'),
                    (SELECT COUNT(*) FROM resource_downloads d WHERE d.company_id = c.id),
                    EXISTS (SELECT 1 FROM founder_intake i WHERE i.company_id = c.id),
                    (SELECT MAX(u.last_login_at) FROM users u WHERE u.company_id = c.id)
                FROM companies c ORDER BY c.name
                """
            )
            per_company = [
                {"company": r[1], "founders": r[2], "open_requests": r[3], "downloads": r[4], "intake_done": r[5],
                 "last_sign_in": iso(r[6])}
                for r in cur.fetchall() if _in_scope(allowed, r[0])
            ]
            audit = _audit_rows(cur, user, limit=12) if has_perm(user, "audit.view") else []
    return {"counts": counts, "top_resources": top, "companies": per_company, "recent_admin_actions": audit}


def _pending_count(cur) -> int:
    cur.execute(
        """
        SELECT (SELECT COUNT(*) FROM resources WHERE status = 'in_review')
             + (SELECT COUNT(*) FROM events WHERE approval = 'pending')
             + (SELECT COUNT(*) FROM connect_entries WHERE approval = 'pending')
             + (SELECT COUNT(*) FROM sector_updates WHERE approval = 'pending')
        """
    )
    return cur.fetchone()[0]


# ---------------------------------------------------------------- companies & founders
class CompanyDetails(BaseModel):
    """Company record details shown on the company card (from the example.org portfolio page)."""
    city: str | None = Field(default=None, max_length=80)
    fund: str | None = Field(default=None, max_length=120)
    invested: str | None = Field(default=None, max_length=40)  # for example "May 2021"
    website: str | None = Field(default=None, max_length=300)
    about: str | None = Field(default=None, max_length=600)


class CompanyIn(CompanyDetails):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=60)
    sector: str | None = Field(default=None, max_length=200)  # one or more comma-separated sector tags
    stage: str | None = Field(default=None, max_length=40)
    # Optional: invite the first founder in the same step (meeting 23 Oct: analysts set the company up).
    founder: "FounderIn | None" = None


class CompanyPatch(CompanyDetails):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    sector: str | None = Field(default=None, max_length=200)
    stage: str | None = Field(default=None, max_length=40)
    status: str | None = None  # active | exited


class PersonIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class FounderIn(PersonIn):
    title: str | None = Field(default=None, max_length=80)  # for example "Co-founder & CEO"
    phone: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=600)  # personal line added to the invite
    send_email: bool = True


class StaffIn(PersonIn):
    level: str = "analyst"  # admin | analyst


class UserPatch(BaseModel):
    active: bool | None = None
    reset_password: bool = False
    title: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None  # a founder's sign-in address (staff correct it after a typo or a change)


class AssignmentsIn(BaseModel):
    relationship_partner: str | None = Field(default=None, max_length=120)
    portfolio_analyst: str | None = Field(default=None, max_length=120)


class PlaybookIn(BaseModel):
    owner_name: str | None = Field(default=None, max_length=120)


class TaskCreate(BaseModel):
    phase_no: int = Field(ge=1, le=4)
    title: str = Field(min_length=3, max_length=160)
    resource_slug: str | None = Field(default=None, max_length=80)


def _company_or_404(cur, company_id: int) -> tuple:
    cur.execute("SELECT id, name, slug FROM companies WHERE id = %s", (company_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Company not found")
    return row


@router.get("/companies")
def list_companies(user: dict = Depends(need("companies.view"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug, name, sector, stage, created_at, city, fund, invested, website, about, status, legal_name, logo_data FROM companies ORDER BY status, name")
            companies = cur.fetchall()
            cur.execute(
                """
                SELECT u.id, u.company_id, u.full_name, u.email, u.active, u.created_at, u.last_login_at, u.title, u.phone
                FROM users u WHERE u.account_type = 'founder' ORDER BY u.full_name
                """
            )
            founders = cur.fetchall()
            cur.execute(
                """
                SELECT DISTINCT ON (company_id, role) company_id, role, person, effective_from, assigned_by
                FROM company_assignments ORDER BY company_id, role, effective_from DESC, id DESC
                """
            )
            assignments = cur.fetchall()
            cur.execute("SELECT company_id, progress_pct, current_phase, owner_name FROM playbook_progress")
            playbooks = {r[0]: r for r in cur.fetchall()}
            cur.execute("SELECT company_id, COUNT(*) FILTER (WHERE done), COUNT(*) FROM playbook_tasks GROUP BY company_id")
            task_counts = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    allowed = company_scope(user, "companies.view")  # Admins and Analysts: assigned companies only
    out = []
    for cid, slug, name, sector, stage, created, city, fund, invested, website, about, cstatus, legal_name, logo in companies:
        if not _in_scope(allowed, cid):
            continue
        pb = playbooks.get(cid)
        out.append({
            "id": cid, "slug": slug, "name": name, "sector": sector, "stage": stage, "created_at": iso(created),
            "city": city, "fund": fund, "invested": invested, "website": website, "about": about, "status": cstatus,
            "legal_name": legal_name, "logo": logo or "",
            "founders": [
                {"id": f[0], "full_name": f[2], "email": f[3], "active": f[4], "created_at": iso(f[5]), "last_sign_in": iso(f[6]),
                 "title": f[7], "phone": f[8]}
                for f in founders if f[1] == cid
            ],
            "team": {a[1]: {"person": a[2], "since": iso(a[3]), "assigned_by": a[4]} for a in assignments if a[0] == cid},
            "playbook": {
                "progress_pct": pb[1] if pb else 0, "current_phase": pb[2] if pb else phase_label(1),
                "owner_name": pb[3] if pb else None,
                "tasks_done": task_counts.get(cid, (0, 0))[0], "tasks_total": task_counts.get(cid, (0, 0))[1],
            },
            "can": {
                "founders": has_perm(user, "founders.manage") and _in_scope(company_scope(user, "founders.manage"), cid),
                "team": has_perm(user, "team.assign") and _in_scope(company_scope(user, "team.assign"), cid),
                "playbook": has_perm(user, "playbooks.manage") and _in_scope(company_scope(user, "playbooks.manage"), cid),
                "edit": has_perm(user, "companies.add") and _in_scope(company_scope(user, "companies.add"), cid),
            },
        })
    return out


def _clean_details(values: dict[str, Any]) -> dict[str, Any]:
    """Trim text; an empty string clears a field. The website must be a web address."""
    out = {}
    for key, val in values.items():
        if isinstance(val, str):
            val = val.strip() or None
        out[key] = val
    site = out.get("website")
    if site and not site.lower().startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Website must start with https://")
    return out


@router.post("/companies")
def create_company(body: CompanyIn, user: dict = Depends(need("companies.add"))) -> dict[str, Any]:
    if not SLUG_RE.fullmatch(body.slug):
        raise HTTPException(status_code=422, detail="Short ID must be lowercase letters, digits and dashes")
    d = _clean_details(body.model_dump(include={"sector", "stage", "city", "fund", "invested", "website", "about"}))
    if d["stage"] and d["stage"] not in STAGES:
        raise HTTPException(status_code=422, detail=f"Stage must be one of: {', '.join(STAGES)}")
    if d["sector"]:
        d["sector"] = ", ".join(sector_tags(d["sector"]))
    invite = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM companies WHERE slug = %s", (body.slug,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="A company with this short ID already exists")
            cur.execute(
                """
                INSERT INTO companies (slug, name, sector, stage, city, fund, invested, website, about)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (body.slug, body.name.strip(), d["sector"], d["stage"], d["city"], d["fund"], d["invested"],
                 d["website"], d["about"]),
            )
            cid = cur.fetchone()[0]
            seed_template_tasks(cur, cid, created_by=user["full_name"])
            sync_progress(cur, cid)
            if company_scope(user, "companies.add") is not None:
                # An Admin or Analyst who sets a company up is its first relationship manager or analyst,
                # so the company is in their scope straight away (the Super Admin can change it later).
                role = "relationship_partner" if "admin" in (user.get("roles") or []) else "portfolio_analyst"
                cur.execute(
                    "INSERT INTO company_assignments (company_id, role, person, assigned_by, user_id) VALUES (%s, %s, %s, %s, %s)",
                    (cid, role, user["full_name"], user["full_name"], user["id"]),
                )
            _audit(cur, user, "company.create", body.name.strip(), body.model_dump(exclude={"founder"}), cid)
            if body.founder is not None:
                invite = invite_founder(cur, user, cid, body.name.strip(), body.founder)
        conn.commit()
    if invite and invite["outbox_id"]:
        deliver([invite["outbox_id"]])
        with get_conn() as conn:
            with conn.cursor() as cur:
                invite["email_status"] = outbox_status(cur, [invite["outbox_id"]])[0]
    return {"id": cid, "invite": invite, "email_mode": "live" if email_configured() else "test"}


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyPatch, user: dict = Depends(need("companies.add"))) -> dict[str, str]:
    # Fields sent as "" are cleared; fields left out are kept.
    changes = _clean_details(body.model_dump(exclude_unset=True))
    if "name" in changes and not changes["name"]:
        raise HTTPException(status_code=422, detail="The company name cannot be empty")
    if "status" in changes and changes["status"] is None:
        del changes["status"]
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    require_company(user, "companies.add", company_id)
    if "status" in changes and company_scope(user, "companies.add") is not None:
        raise HTTPException(status_code=403, detail="Only the Super Admin marks a company as exited or active")
    if changes.get("stage") and changes["stage"] not in STAGES:
        raise HTTPException(status_code=422, detail=f"Stage must be one of: {', '.join(STAGES)}")
    if changes.get("sector"):
        changes["sector"] = ", ".join(sector_tags(changes["sector"]))
    if changes.get("status") not in (None, "active", "exited"):
        raise HTTPException(status_code=422, detail="Status must be active or exited")
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            for col, val in changes.items():  # columns come from the pydantic model, not user input
                cur.execute(f"UPDATE companies SET {col} = %s WHERE id = %s", (val, company_id))
            _audit(cur, user, "company.status" if list(changes) == ["status"] else "company.update", name, changes, company_id)
        conn.commit()
    return {"status": "updated"}


LOGO_MAX = 300 * 1024
LOGO_TYPES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))


def _logo_type(data: bytes) -> str | None:
    for magic, mime in LOGO_TYPES:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/companies/{company_id}/logo")
async def upload_company_logo(company_id: int, file: UploadFile = File(...), user: dict = Depends(need("companies.add"))) -> dict[str, str]:
    """A company's logo: PNG, JPEG or WebP up to 300 KB. It shows in the workspace and the founder portal."""
    require_company(user, "companies.add", company_id)
    data = await file.read(LOGO_MAX + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Choose an image file for the logo")
    if len(data) > LOGO_MAX:
        raise HTTPException(status_code=413, detail="The logo must be 300 KB or smaller")
    mime = _logo_type(data)
    if not mime:
        raise HTTPException(status_code=422, detail="The logo must be a PNG, JPEG or WebP image")
    import base64
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            cur.execute("UPDATE companies SET logo_data = %s WHERE id = %s", (uri, company_id))
            _audit(cur, user, "company.logo", name, {"file": (file.filename or "")[:120], "bytes": len(data)}, company_id)
        conn.commit()
    return {"status": "saved", "logo": uri}


@router.delete("/companies/{company_id}/logo")
def remove_company_logo(company_id: int, user: dict = Depends(need("companies.add"))) -> dict[str, str]:
    require_company(user, "companies.add", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            cur.execute("UPDATE companies SET logo_data = NULL WHERE id = %s", (company_id,))
            _audit(cur, user, "company.logo", name, {"removed": True}, company_id)
        conn.commit()
    return {"status": "removed"}


def invite_founder(cur, user: dict[str, Any], company_id: int, company: str, body: FounderIn) -> dict[str, Any]:
    """Create a founder account with no usable password and a single-use invite link (emailed unless
    send_email is false). The link is also returned once, for WhatsApp or copying."""
    email = body.email.lower()
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail=f"{email} already has an account")
    _, unusable = _temp_password()  # nobody knows this password; the founder sets one with the link
    phone = (body.phone or "").strip() or None
    cur.execute(
        "INSERT INTO users (email, password_hash, full_name, account_type, company_id, title, phone) "
        "VALUES (%s, %s, %s, 'founder', %s, %s, %s) RETURNING id",
        (email, unusable, body.full_name.strip(), company_id, (body.title or "").strip() or None, phone),
    )
    uid = cur.fetchone()[0]
    cur.execute("INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'founder', %s)", (uid, user["email"]))
    token = make_token(cur, uid, "invite", user["full_name"])
    url = link("invite", token)
    subject, text, wa = invite_message(body.full_name, company, user["full_name"], url, body.note)
    mid = queue_email(cur, email, body.full_name.strip(), subject, text, "invite", user["full_name"], company_id, phone) if body.send_email else None
    _audit(cur, user, "founder.invite", email, {"company": company, "emailed": body.send_email}, company_id)
    return {"id": uid, "email": email, "company": company, "invite_link": url, "outbox_id": mid,
            "whatsapp_url": whatsapp_url(phone, wa), "mailto_url": mailto_url(email, subject, text)}


@router.post("/companies/{company_id}/founders")
def add_founder(company_id: int, body: FounderIn, user: dict = Depends(need("founders.manage"))) -> dict[str, Any]:
    require_company(user, "founders.manage", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            result = invite_founder(cur, user, company_id, name, body)
        conn.commit()
    if result["outbox_id"]:
        deliver([result["outbox_id"]])
        with get_conn() as conn:
            with conn.cursor() as cur:
                result["email_status"] = outbox_status(cur, [result["outbox_id"]])[0]
    result["email_mode"] = "live" if email_configured() else "test"
    return result


def _staff_tier(cur, user_id: int) -> str | None:
    cur.execute("SELECT role_code FROM user_roles WHERE user_id = %s", (user_id,))
    roles = {r[0] for r in cur.fetchall()}
    for code in (SUPER_ADMIN, "admin", "analyst"):
        if code in roles:
            return code
    return None


def _can_manage_staff(cur, user: dict[str, Any], target_id: int) -> None:
    """Super Admin manages everyone; Admins manage analysts on their companies (or not yet assigned)."""
    tier = _staff_tier(cur, target_id)
    if tier == SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="The Super Admin's account is changed only by the Super Admin")
    if tier == "admin":
        require_perm(user, "admins.manage")
        return
    require_perm(user, "staff.manage")
    allowed = company_scope(user, "founders.manage")
    if allowed is None:
        return
    cur.execute("SELECT reports_to FROM users WHERE id = %s", (target_id,))
    row = cur.fetchone()
    if row and row[0] == user["id"]:
        return  # the analyst reports to this Admin
    cur.execute(
        """
        SELECT company_id FROM (SELECT DISTINCT ON (company_id, role) company_id, user_id FROM company_assignments
            ORDER BY company_id, role, effective_from DESC, id DESC) a WHERE a.user_id = %s
        """,
        (target_id,),
    )
    theirs = {r[0] for r in cur.fetchall()}
    if theirs and not (theirs & allowed):
        raise HTTPException(status_code=403, detail="This analyst works on other companies")


@router.patch("/users/{user_id}")
def update_user(
    user_id: int, body: UserPatch, authorization: str | None = Header(default=None),
    user: dict = Depends(need("founders.manage", "staff.manage", "admins.manage")),
) -> dict[str, Any]:
    if user_id == user["id"] and body.active is False:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    result: dict[str, Any] = {"status": "updated"}
    ids_to_send: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email, account_type, company_id FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            email, account_type, company_id = row
            if account_type == "founder":
                require_company(user, "founders.manage", company_id)
            elif user_id != user["id"]:
                _can_manage_staff(cur, user, user_id)
            if body.title is not None or body.phone is not None:
                for col, val in (("title", body.title), ("phone", body.phone)):
                    if val is not None:  # column names are fixed here
                        cur.execute(f"UPDATE users SET {col} = %s WHERE id = %s", (val.strip() or None, user_id))
                _audit(cur, user, "user.contact", email, None, company_id)
            if body.full_name is not None:
                cur.execute("UPDATE users SET full_name = %s WHERE id = %s", (body.full_name.strip(), user_id))
                _audit(cur, user, "user.rename", email, None, company_id)
            if body.email is not None and str(body.email).lower() != email.lower():
                if account_type != "founder":
                    raise HTTPException(status_code=422, detail="Only a founder's email can be changed here")
                new_email = str(body.email).lower()
                cur.execute("SELECT 1 FROM users WHERE lower(email) = %s AND id <> %s", (new_email, user_id))
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="Another account already uses this email")
                cur.execute("UPDATE users SET email = %s WHERE id = %s", (new_email, user_id))
                cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))  # sign in again with the new address
                _audit(cur, user, "user.email", new_email, {"from": email}, company_id)
                email = new_email
            if body.active is not None:
                cur.execute("UPDATE users SET active = %s WHERE id = %s", (body.active, user_id))
                if not body.active:
                    cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
                _audit(cur, user, "user.activate" if body.active else "user.deactivate", email, None, company_id)
            if body.reset_password and account_type == "founder":
                # Founders get a single-use reset link (emailed, and returned once for WhatsApp or copying).
                cur.execute("SELECT full_name, phone FROM users WHERE id = %s", (user_id,))
                fname, phone = cur.fetchone()
                _, unusable = _temp_password()
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (unusable, user_id))
                cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
                cur.execute("DELETE FROM login_failures WHERE email = %s", (email,))
                token = make_token(cur, user_id, "reset", user["full_name"])
                url = link("reset", token)
                subject, text, wa = reset_message(fname, user["full_name"], url)
                mid = queue_email(cur, email, fname, subject, text, "reset", user["full_name"], company_id, phone)
                _audit(cur, user, "user.reset_password", email, {"link": True}, company_id)
                result.update({"reset_link": url, "outbox_id": mid, "whatsapp_url": whatsapp_url(phone, wa),
                               "mailto_url": mailto_url(email, subject, text)})
                ids_to_send.append(mid)
            elif body.reset_password:
                temp, pw_hash = _temp_password()
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, user_id))
                cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))
                cur.execute("DELETE FROM login_failures WHERE email = %s", (email,))
                _audit(cur, user, "user.reset_password", email, None, company_id)
                result["temporary_password"] = temp
        conn.commit()
    if ids_to_send:
        deliver(ids_to_send)
        with get_conn() as conn:
            with conn.cursor() as cur:
                result["email_status"] = outbox_status(cur, ids_to_send)[0]
        result["email_mode"] = "live" if email_configured() else "test"
    return result


@router.put("/companies/{company_id}/team")
def set_team(company_id: int, body: AssignmentsIn, user: dict = Depends(need("team.assign"))) -> dict[str, str]:
    require_company(user, "team.assign", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            for role in ASSIGNMENT_ROLES:
                person = (getattr(body, role) or "").strip()
                if not person:
                    continue
                cur.execute(
                    """
                    SELECT person FROM company_assignments WHERE company_id = %s AND role = %s
                    ORDER BY effective_from DESC, id DESC LIMIT 1
                    """,
                    (company_id, role),
                )
                current = cur.fetchone()
                if current and current[0] == person:
                    continue
                cur.execute(
                    """
                    SELECT u.id, u.full_name, ARRAY(SELECT role_code FROM user_roles r WHERE r.user_id = u.id)
                    FROM users u WHERE u.account_type = 'staff' AND u.active AND lower(trim(u.full_name)) = lower(%s) LIMIT 1
                    """,
                    (person,),
                )
                staff = cur.fetchone()
                if not staff:
                    raise HTTPException(status_code=422, detail=f"{person} has no active Demo Ventures account. Choose someone from the list")
                if role == "relationship_partner" and not set(staff[2]) & {"admin", "super_admin"}:
                    raise HTTPException(status_code=422, detail="The relationship manager must be an Admin")
                person = staff[1]
                cur.execute(
                    "INSERT INTO company_assignments (company_id, role, person, assigned_by, user_id) VALUES (%s, %s, %s, %s, %s)",
                    (company_id, role, person, user["full_name"], staff[0] if staff else None),
                )
                _audit(cur, user, "team.assign", name, {"role": role, "person": person, "previous": current[0] if current else None}, company_id)
        conn.commit()
    return {"status": "updated"}


@router.get("/companies/{company_id}/team/history")
def team_history(company_id: int, user: dict = Depends(need("companies.view"))) -> list[dict[str, Any]]:
    require_company(user, "companies.view", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _company_or_404(cur, company_id)
            cur.execute(
                """
                SELECT role, person, effective_from, assigned_by FROM company_assignments
                WHERE company_id = %s ORDER BY effective_from DESC, id DESC
                """,
                (company_id,),
            )
            rows = cur.fetchall()
    return [{"role": r[0], "person": r[1], "since": iso(r[2]), "assigned_by": r[3]} for r in rows]


@router.put("/companies/{company_id}/playbook")
def set_playbook(company_id: int, body: PlaybookIn, user: dict = Depends(need("playbooks.manage"))) -> dict[str, Any]:
    """Set the Demo Ventures owner. Progress and phase are calculated from the task list."""
    require_company(user, "playbooks.manage", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            owner = (body.owner_name or "").strip() or None
            if owner:
                cur.execute("SELECT full_name FROM users WHERE account_type = 'staff' AND active AND lower(full_name) = lower(%s)", (owner,))
                found = cur.fetchone()
                if not found:
                    raise HTTPException(status_code=422, detail=f"{owner} has no active Demo Ventures account. Choose someone from the list")
                owner = found[0]
            pct, phase = sync_progress(cur, company_id)
            cur.execute(
                "UPDATE playbook_progress SET owner_name = %s, updated_at = NOW() WHERE company_id = %s",
                (owner, company_id),
            )
            _audit(cur, user, "playbook.owner", name, {"owner_name": body.owner_name}, company_id)
        conn.commit()
    return {"status": "updated", "progress_pct": pct, "current_phase": phase}


@router.get("/companies/{company_id}/tasks")
def list_tasks(company_id: int, user: dict = Depends(need("playbooks.manage"))) -> dict[str, Any]:
    require_company(user, "playbooks.manage", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _company_or_404(cur, company_id)
            cur.execute(
                """
                SELECT t.id, t.phase_no, t.title, t.done, t.done_at, t.done_by, t.resource_slug, r.title
                FROM playbook_tasks t LEFT JOIN resources r ON r.slug = t.resource_slug
                WHERE t.company_id = %s ORDER BY t.phase_no, t.sort_order, t.id
                """,
                (company_id,),
            )
            rows = cur.fetchall()
            cur.execute("SELECT slug, title FROM resources WHERE status = 'approved' AND slug NOT LIKE 'upload-%%' ORDER BY title")
            resources = [{"slug": a, "title": b} for a, b in cur.fetchall()]
    return {
        "phases": [{"no": n, "label": f"{name} · {days}"} for n, name, days in PHASES],
        "tasks": [
            {"id": r[0], "phase_no": r[1], "title": r[2], "done": r[3], "done_at": iso(r[4]), "done_by": r[5],
             "resource_slug": r[6], "resource_title": r[7]}
            for r in rows
        ],
        "resources": resources,
    }


@router.post("/companies/{company_id}/tasks")
def add_task(company_id: int, body: TaskCreate, user: dict = Depends(need("playbooks.manage"))) -> dict[str, Any]:
    require_company(user, "playbooks.manage", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            _, name, _ = _company_or_404(cur, company_id)
            if body.resource_slug:
                cur.execute("SELECT 1 FROM resources WHERE slug = %s AND status = 'approved'", (body.resource_slug,))
                if not cur.fetchone():
                    raise HTTPException(status_code=422, detail="Linked resource must be an approved resource")
            cur.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM playbook_tasks WHERE company_id = %s AND phase_no = %s",
                (company_id, body.phase_no),
            )
            order = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO playbook_tasks (company_id, phase_no, title, sort_order, resource_slug, created_by)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (company_id, body.phase_no, body.title.strip(), order, body.resource_slug or None, user["full_name"]),
            )
            tid = cur.fetchone()[0]
            pct, phase = sync_progress(cur, company_id)
            _audit(cur, user, "playbook.task_add", name, {"phase": body.phase_no, "title": body.title}, company_id)
        conn.commit()
    return {"id": tid, "progress_pct": pct, "current_phase": phase}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, user: dict = Depends(need("playbooks.manage"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT t.company_id, c.name, t.title FROM playbook_tasks t JOIN companies c ON c.id = t.company_id WHERE t.id = %s", (task_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Task not found")
            require_company(user, "playbooks.manage", row[0])
            cur.execute("DELETE FROM playbook_tasks WHERE id = %s", (task_id,))
            pct, phase = sync_progress(cur, row[0])
            _audit(cur, user, "playbook.task_remove", row[1], {"title": row[2]}, row[0])
        conn.commit()
    return {"status": "removed", "progress_pct": pct, "current_phase": phase}


# ---------------------------------------------------------------- sector updates (written by hand in alpha)
class SectorUpdateIn(Audience):
    label: str
    title: str = Field(min_length=5, max_length=160)
    summary: str = Field(min_length=10, max_length=800)
    source: str = Field(min_length=2, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    expires_in_days: int = Field(default=30, ge=1, le=180)


class SectorUpdatePatch(BaseModel):
    action: str  # withdraw | resubmit
    title: str | None = Field(default=None, min_length=5, max_length=160)
    summary: str | None = Field(default=None, min_length=10, max_length=800)
    source_url: str | None = Field(default=None, max_length=500)


@router.get("/sector-updates")
def list_updates(user: dict = Depends(need("news.publish"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id, c.name, s.label, s.title, s.summary, s.source, s.source_url, s.published_at, s.expires_at,
                    s.published_by, (s.expires_at IS NULL OR s.expires_at > NOW()), s.approval, s.review_note,
                    s.company_id, s.target_company_ids, s.target_sectors, s.target_stages
                FROM sector_updates s LEFT JOIN companies c ON c.id = s.company_id
                WHERE (%s::int[] IS NULL OR s.company_id IS NULL OR s.company_id = ANY(%s::int[]))
                ORDER BY 11 DESC, s.published_at DESC LIMIT 100
                """, _scope_ids(user)
            )
            rows = cur.fetchall()
            names = company_names(cur)
    return [
        {"id": r[0], "company": describe(r[1], r[14], r[15], r[16], names), "label": r[2], "title": r[3], "summary": r[4],
         "source": r[5], "source_url": r[6], "published_at": iso(r[7]), "expires_at": iso(r[8]), "published_by": r[9],
         "live": r[10], "approval": r[11], "review_note": r[12], "company_id": r[13], "target_company_ids": r[14],
         "target_sectors": r[15], "target_stages": r[16], "can_change": _may_change(user, r[13], r[9])}
        for r in rows
    ]


@router.post("/sector-updates")
def publish_update(body: SectorUpdateIn, user: dict = Depends(need("news.publish"))) -> dict[str, Any]:
    label = body.label.upper()
    if label not in UPDATE_LABELS:
        raise HTTPException(status_code=422, detail=f"Type must be one of {', '.join(UPDATE_LABELS)}")
    if body.source_url and not body.source_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Source link must start with http(s)://")
    approval = _initial_approval(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            aud = clean_audience(cur, body, company_scope(user, "companies.view"))
            if aud["company_id"] is not None:
                _company_or_404(cur, aud["company_id"])
                cur.execute("SELECT sector FROM companies WHERE id = %s", (aud["company_id"],))
                sector = cur.fetchone()[0]
            else:
                sector = ", ".join(aud["target_sectors"]) or None
            cur.execute(
                """
                INSERT INTO sector_updates (company_id, label, title, summary, sector, source, source_url, published_by,
                    published_at, expires_at, approval, target_company_ids, target_sectors, target_stages)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + make_interval(days => %s), %s, %s, %s, %s) RETURNING id
                """,
                (aud["company_id"], label, body.title.strip(), body.summary.strip(), sector, body.source.strip(),
                 body.source_url, user["full_name"], body.expires_in_days, approval,
                 aud["target_company_ids"], aud["target_sectors"], aud["target_stages"]),
            )
            uid = cur.fetchone()[0]
            _audit(cur, user, "sector_update.publish", body.title.strip(),
                   {"source": body.source, "approval": approval, **{k: v for k, v in aud.items() if v}}, aud["company_id"])
        conn.commit()
    return {"id": uid, "approval": approval}


@router.patch("/sector-updates/{update_id}")
def change_update(update_id: int, body: SectorUpdatePatch, user: dict = Depends(need("news.publish"))) -> dict[str, str]:
    if body.action not in ("withdraw", "resubmit"):
        raise HTTPException(status_code=422, detail="action must be withdraw or resubmit")
    if body.action == "resubmit":
        return _resubmit_update(update_id, body, user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, published_by FROM sector_updates WHERE id = %s", (update_id,))
            found = cur.fetchone()
            if not found:
                raise HTTPException(status_code=404, detail="Update not found")
            if not _may_change(user, found[0], found[1]):
                raise HTTPException(status_code=403, detail="You are not assigned to this company")
            cur.execute("UPDATE sector_updates SET expires_at = NOW() WHERE id = %s RETURNING title, company_id", (update_id,))
            row = cur.fetchone()
            _audit(cur, user, "sector_update.withdraw", row[0], None, row[1])
        conn.commit()
    return {"status": "withdrawn"}


# ---------------------------------------------------------------- events
def _resubmit_update(update_id: int, body: SectorUpdatePatch, user: dict[str, Any]) -> dict[str, str]:
    """A returned update, corrected by its team, goes back to the Super Admin."""
    if body.source_url and not body.source_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Source link must start with http(s)://")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, approval, title, published_by FROM sector_updates WHERE id = %s", (update_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Update not found")
            if not _may_change(user, row[0], row[3]):
                raise HTTPException(status_code=403, detail="You are not assigned to this company")
            if row[1] != "returned":
                raise HTTPException(status_code=422, detail="Only a returned update can be resubmitted")
            for col in ("title", "summary", "source_url"):  # fixed column names
                val = getattr(body, col)
                if val is not None:
                    cur.execute(f"UPDATE sector_updates SET {col} = %s WHERE id = %s", (val.strip() or None, update_id))
            cur.execute("UPDATE sector_updates SET approval = %s, review_note = NULL WHERE id = %s",
                        (_initial_approval(user), update_id))
            _audit(cur, user, "sector_update.resubmit", body.title or row[2], None, row[0])
        conn.commit()
    return {"status": "resubmitted"}


def _clean_link(link: str | None) -> str | None:
    """A meeting link (https://…) or a meeting ID; empty means none."""
    link = (link or "").strip()
    if not link:
        return None
    if link.lower().startswith(("javascript:", "data:", "file:")):
        raise HTTPException(status_code=422, detail="Use an https:// meeting link or a meeting ID")
    if "://" in link and not link.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Meeting links must start with https://")
    return link[:500]


class EventIn(Audience):
    title: str = Field(min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=800)
    location: str = Field(min_length=2, max_length=160)
    starts_at: datetime  # ISO; a value without a time zone is read as IST
    duration_minutes: int = Field(default=60, ge=15, le=10080)  # up to 7 days, for multi-day programmes
    join_link: str | None = Field(default=None, max_length=500)
    rsvp_url: str | None = Field(default=None, max_length=500)  # external events: founders RSVP on this page


class EventPatch(BaseModel):
    action: str | None = None  # cancel | restore | resubmit | edit
    title: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=800)
    location: str | None = Field(default=None, min_length=2, max_length=160)
    # action = edit only: change the date and time, length or audience of an event.
    starts_at: datetime | None = None  # a value without a time zone is read as IST
    duration_minutes: int | None = Field(default=None, ge=15, le=10080)
    rsvp_url: str | None = Field(default=None, max_length=500)  # "" removes it
    company_id: int | None = None  # one company's founders
    for_all_founders: bool | None = None  # true = portfolio-wide (narrowed by the target lists below, if given)
    target_company_ids: list[int] | None = None
    target_sectors: list[str] | None = None
    target_stages: list[str] | None = None
    recording_url: str | None = Field(default=None, max_length=500)
    join_link: str | None = Field(default=None, max_length=500)


@router.get("/events")
def admin_events(user: dict = Depends(need("events.manage"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.title, e.description, e.location, e.starts_at, e.ends_at, c.name, e.recording_url,
                    e.is_sample, e.active, e.created_by,
                    COALESCE(ARRAY(SELECT u.full_name || ' (' || COALESCE(cc.name, 'Demo Ventures') || ')' FROM event_rsvps r
                        JOIN users u ON u.id = r.user_id LEFT JOIN companies cc ON cc.id = u.company_id
                        WHERE r.event_id = e.id AND (%s::int[] IS NULL OR u.company_id = ANY(%s::int[]))
                        ORDER BY r.created_at), '{}'),
                    e.join_link, e.approval, e.review_note, e.pending_join_link, e.pending_link_by, e.pending_recording_url,
                    e.company_id, e.target_company_ids, e.target_sectors, e.target_stages, e.rsvp_url
                FROM events e LEFT JOIN companies c ON c.id = e.company_id
                WHERE (%s::int[] IS NULL OR e.company_id IS NULL OR e.company_id = ANY(%s::int[]))
                ORDER BY e.active DESC, e.starts_at
                """, _scope_ids(user) * 2
            )
            rows = cur.fetchall()
            names = company_names(cur)
    now = datetime.now(timezone.utc)
    return [
        {"id": r[0], "title": r[1], "description": r[2], "location": r[3], "starts_at": iso(r[4]), "ends_at": iso(r[5]),
         "audience": describe(r[6], r[19], r[20], r[21], names), "target_company_ids": r[19], "target_sectors": r[20],
         "target_stages": r[21], "recording_url": r[7], "is_sample": r[8], "active": r[9],
         "created_by": r[10], "attendees": list(r[11]), "past": (r[5] or r[4]) < now, "join_link": r[12],
         "approval": r[13], "review_note": r[14], "pending_join_link": r[15], "pending_link_by": r[16],
         "pending_recording_url": r[17], "company_id": r[18], "rsvp_url": r[22]}
        for r in rows
    ]


@router.post("/events")
def create_event(body: EventIn, user: dict = Depends(need("events.manage"))) -> dict[str, Any]:
    starts = body.starts_at if body.starts_at.tzinfo else body.starts_at.replace(tzinfo=IST)
    if starts < datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Start time must be in the future")
    approval = _initial_approval(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            aud = clean_audience(cur, body, company_scope(user, "companies.view"))
            cur.execute(
                """
                INSERT INTO events (title, description, location, starts_at, ends_at, company_id, created_by, join_link, approval,
                    target_company_ids, target_sectors, target_stages, rsvp_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (body.title.strip(), body.description, body.location.strip(), starts,
                 starts + timedelta(minutes=body.duration_minutes), aud["company_id"], user["full_name"],
                 _clean_link(body.join_link), approval, aud["target_company_ids"], aud["target_sectors"], aud["target_stages"],
                 _rsvp_link(body.rsvp_url)),
            )
            eid = cur.fetchone()[0]
            _audit(cur, user, "event.create", body.title,
                   {"starts_at": starts.isoformat(), "approval": approval, **{k: v for k, v in aud.items() if v}}, aud["company_id"])
        conn.commit()
    return {"id": eid, "approval": approval}


def _rsvp_link(url: str | None) -> str | None:
    """An external event's RSVP page (for example its Luma page): an https address, or nothing."""
    url = (url or "").strip()
    if not url:
        return None
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?", url):
        raise HTTPException(status_code=422, detail="The RSVP link must be a web address starting with https://")
    return url


def _edit_event(cur, user: dict[str, Any], event_id: int, body: EventPatch, title: str, cid: int | None,
                created_by: str | None, approver: bool) -> None:
    """Correct an event's details. An Admin's or Analyst's edit goes back to the Super Admin for approval,
    like any other content they change; the Super Admin's edit is live at once."""
    if not approver and created_by != user["full_name"]:
        raise HTTPException(status_code=403, detail="Only the Super Admin can edit an event someone else added")
    changes: dict[str, Any] = {}
    for col in ("title", "description", "location"):
        val = getattr(body, col)
        if val is not None:
            changes[col] = val.strip() or None
    if body.rsvp_url is not None:
        changes["rsvp_url"] = _rsvp_link(body.rsvp_url)
    if changes.get("title") is None and "title" in changes:
        raise HTTPException(status_code=422, detail="The event title cannot be empty")
    if changes.get("location") is None and "location" in changes:
        raise HTTPException(status_code=422, detail="The event location cannot be empty")
    cur.execute("SELECT starts_at, ends_at FROM events WHERE id = %s", (event_id,))
    old_start, old_end = cur.fetchone()
    if body.starts_at is not None or body.duration_minutes is not None:
        start = old_start
        if body.starts_at is not None:
            start = body.starts_at if body.starts_at.tzinfo else body.starts_at.replace(tzinfo=IST)
            if start < datetime.now(timezone.utc):
                raise HTTPException(status_code=422, detail="Start time must be in the future")
        minutes = body.duration_minutes or max(15, int(((old_end or old_start) - old_start).total_seconds() // 60))
        changes["starts_at"] = start
        changes["ends_at"] = start + timedelta(minutes=minutes)
    if body.for_all_founders or body.company_id is not None:
        aud = clean_audience(cur, Audience(
            company_id=None if body.for_all_founders else body.company_id,
            target_company_ids=body.target_company_ids or [], target_sectors=body.target_sectors or [],
            target_stages=body.target_stages or []), company_scope(user, "companies.view"))
        changes.update(aud)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    for col, val in changes.items():  # column names come from the fixed list above
        cur.execute(f"UPDATE events SET {col} = %s WHERE id = %s", (val, event_id))
    if not approver:
        cur.execute("UPDATE events SET approval = 'pending', review_note = NULL WHERE id = %s", (event_id,))
    _audit(cur, user, "event.edit", changes.get("title") or title,
           {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in changes.items() if k != "description"}
           | {"waits_for_approval": not approver}, changes.get("company_id", cid))


@router.patch("/events/{event_id}")
def change_event(event_id: int, body: EventPatch, user: dict = Depends(need("events.manage"))) -> dict[str, str]:
    if body.action not in (None, "cancel", "restore", "resubmit", "edit"):
        raise HTTPException(status_code=422, detail="action must be cancel, restore, resubmit or edit")
    if body.recording_url and not body.recording_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="Recording link must start with http(s)://")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, company_id, created_by FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Event not found")
            title, cid, created_by = row
            approver = has_perm(user, "content.approve")
            if cid is not None and not _in_scope(company_scope(user, "companies.view"), cid):
                raise HTTPException(status_code=403, detail="You are not assigned to this company")
            if body.action == "resubmit":
                cur.execute("SELECT approval FROM events WHERE id = %s", (event_id,))
                if cur.fetchone()[0] != "returned":
                    raise HTTPException(status_code=422, detail="Only a returned event can be resubmitted")
                for col in ("title", "description", "location"):  # fixed column names
                    val = getattr(body, col)
                    if val is not None:
                        cur.execute(f"UPDATE events SET {col} = %s WHERE id = %s", (val.strip() or None, event_id))
                cur.execute("UPDATE events SET approval = %s, review_note = NULL WHERE id = %s", (_initial_approval(user), event_id))
                _audit(cur, user, "event.resubmit", body.title or title, None, cid)
                body.action = None
            if body.action == "edit":
                _edit_event(cur, user, event_id, body, title, cid, created_by, approver)
                body.action = None
            if body.action:
                if not approver and created_by != user["full_name"]:
                    raise HTTPException(status_code=403, detail="Only the Super Admin can cancel or restore an event someone else added")
                cur.execute("UPDATE events SET active = %s WHERE id = %s", (body.action == "restore", event_id))
                _audit(cur, user, f"event.{body.action}", title, None, cid)
            if body.recording_url is not None:
                if approver:
                    cur.execute("UPDATE events SET recording_url = %s, pending_recording_url = NULL WHERE id = %s",
                                (body.recording_url or None, event_id))
                elif not body.recording_url:
                    raise HTTPException(status_code=422, detail="Ask the Super Admin to remove a recording")
                else:  # a recording is new content for founders: it waits for approval
                    cur.execute("UPDATE events SET pending_recording_url = %s, pending_recording_by = %s, pending_recording_at = NOW() "
                                "WHERE id = %s", (body.recording_url, user["full_name"], event_id))
                _audit(cur, user, "event.recording", title, {"recording_url": body.recording_url, "waits_for_approval": not approver}, cid)
            if body.join_link is not None:
                link = _clean_link(body.join_link)
                if has_perm(user, "content.approve"):
                    cur.execute("UPDATE events SET join_link = %s, pending_join_link = NULL, pending_link_by = NULL, "
                                "pending_link_at = NULL WHERE id = %s", (link, event_id))
                elif link is None:
                    raise HTTPException(status_code=422, detail="Ask the Super Admin to remove a join link")
                else:
                    # The event stays visible to founders with its current link; the new one waits for approval.
                    cur.execute("UPDATE events SET pending_join_link = %s, pending_link_by = %s, pending_link_at = NOW() "
                                "WHERE id = %s", (link, user["full_name"], event_id))
                _audit(cur, user, "event.join_link", title, {"link": link, "waits_for_approval": not has_perm(user, "content.approve")}, cid)
        conn.commit()
    return {"status": "updated"}


# ---------------------------------------------------------------- Connect directory
class ConnectIn(BaseModel):
    network_group: str
    subcategory: str = Field(min_length=2, max_length=80)
    display_name: str = Field(min_length=2, max_length=120)
    role_title: str = Field(min_length=2, max_length=120)
    organization: str = Field(min_length=2, max_length=120)
    about: str = Field(default="", max_length=600)
    skills: list[str] = Field(default_factory=list, max_length=8)
    website: str = Field(default="", max_length=300)
    stage: str = Field(default="", max_length=120)
    cheque_size: str = Field(default="", max_length=60)


def _clean_site(url: str | None) -> str | None:
    """A Connect profile's website: an http(s) address, or nothing."""
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    if not re.fullmatch(r"https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?", url):
        raise HTTPException(status_code=422, detail="Website must be a web address such as https://example.com")
    return url


class ConnectPatch(BaseModel):
    active: bool | None = None
    about: str | None = Field(default=None, max_length=600)
    role_title: str | None = Field(default=None, min_length=2, max_length=120)
    organization: str | None = Field(default=None, min_length=2, max_length=120)
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    subcategory: str | None = Field(default=None, min_length=2, max_length=80)
    network_group: str | None = None
    skills: list[str] | None = Field(default=None, max_length=8)
    website: str | None = Field(default=None, max_length=300)
    stage: str | None = Field(default=None, max_length=120)
    cheque_size: str | None = Field(default=None, max_length=60)


@router.get("/connect")
def admin_connect(user: dict = Depends(need("connect.manage"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.network_group, e.subcategory, e.display_name, e.role_title, e.organization, e.why_relevant,
                    e.skills, e.is_sample, e.active, e.created_by,
                    (SELECT COUNT(*) FROM founder_help h WHERE h.connect_entry_id = e.id), e.approval, e.review_note, e.website, e.stage, e.cheque_size
                FROM connect_entries e ORDER BY e.network_group, e.subcategory, e.display_name
                """
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "network_group": r[1], "subcategory": r[2], "display_name": r[3], "role_title": r[4],
         "organization": r[5], "about": r[6], "skills": r[7] or [], "is_sample": r[8], "active": r[9],
         "created_by": r[10], "introductions": r[11], "approval": r[12], "review_note": r[13], "website": r[14] or "", "stage": r[15] or "", "cheque_size": r[16] or ""}
        for r in rows
    ]


def _insert_connect(cur, user: dict[str, Any], body: ConnectIn, approval: str) -> int:
    if body.network_group not in CONNECT_GROUPS:
        raise HTTPException(status_code=422, detail=f"Network must be one of: {', '.join(CONNECT_GROUPS)}")
    skills = [k.strip()[:40] for k in body.skills if k.strip()]
    cur.execute(
        """
        INSERT INTO connect_entries (network_group, subcategory, display_name, role_title, organization,
            why_relevant, skills, is_sample, active, created_by, approval, website, stage, cheque_size)
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, TRUE, %s, %s, %s, %s, %s) RETURNING id
        """,
        (body.network_group, body.subcategory.strip(), body.display_name.strip(), body.role_title.strip(),
         body.organization.strip(), body.about.strip(), skills, user["full_name"], approval, _clean_site(body.website),
         body.stage.strip() or None, body.cheque_size.strip() or None),
    )
    return cur.fetchone()[0]


@router.post("/connect")
def add_connect(body: ConnectIn, user: dict = Depends(need("connect.manage"))) -> dict[str, Any]:
    approval = _initial_approval(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cid = _insert_connect(cur, user, body, approval)
            _audit(cur, user, "connect.add", body.display_name, {"group": body.network_group, "approval": approval})
        conn.commit()
    return {"id": cid, "approval": approval}


@router.patch("/connect/{entry_id}")
def change_connect(entry_id: int, body: ConnectPatch, user: dict = Depends(need("connect.manage"))) -> dict[str, str]:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    column = {"active": "active", "about": "why_relevant", "role_title": "role_title", "organization": "organization",
              "display_name": "display_name", "subcategory": "subcategory", "network_group": "network_group",
              "skills": "skills", "website": "website", "stage": "stage", "cheque_size": "cheque_size"}
    if "website" in changes:
        changes["website"] = _clean_site(changes["website"]) or ""
    if "network_group" in changes and changes["network_group"] not in CONNECT_GROUPS:
        raise HTTPException(status_code=422, detail=f"Network must be one of: {', '.join(CONNECT_GROUPS)}")
    if "skills" in changes:
        changes["skills"] = [k.strip()[:40] for k in changes["skills"] if k.strip()]
    for key in ("about", "role_title", "organization", "display_name", "subcategory", "stage", "cheque_size"):
        if key in changes:
            changes[key] = changes[key].strip()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT display_name FROM connect_entries WHERE id = %s", (entry_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Connect profile not found")
            for key, val in changes.items():  # column names come from the fixed map above
                cur.execute(f"UPDATE connect_entries SET {column[key]} = %s WHERE id = %s", (val, entry_id))
            if changes.keys() & {"display_name", "organization"}:
                # A sample slot rewritten with a real person or firm is no longer a sample.
                cur.execute("UPDATE connect_entries SET is_sample = FALSE WHERE id = %s", (entry_id,))
            if (changes.keys() - {"active"} or changes.get("active") is True) and not has_perm(user, "content.approve"):
                cur.execute("UPDATE connect_entries SET approval = 'pending' WHERE id = %s", (entry_id,))
            action = "connect.update" if "active" not in changes else ("connect.show" if changes["active"] else "connect.hide")
            _audit(cur, user, action, row[0], {k: v for k, v in changes.items() if k != "about"})
        conn.commit()
    return {"status": "updated"}


CONNECT_CSV_COLUMNS = ["network_group", "subcategory", "display_name", "role_title", "organization", "about", "skills", "website"]


@router.get("/connect/bulk-template")
def connect_template(user: dict = Depends(need("connect.manage"))) -> Response:
    sample = [CONNECT_CSV_COLUMNS, ["Operational Support Network", "CA & Tax", "Example Partners LLP", "Chartered accountants",
                                    "Example Partners LLP", "Startup tax, GST and FEMA filings for growth-stage companies.", "GST; FEMA; Startup tax",
                                    "https://example.com"]]
    buf = io.StringIO()
    csv.writer(buf).writerows(sample)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="connect-profiles-template.csv"'})


def read_csv_upload(data: bytes, columns: list[str], optional: tuple[str, ...] = ()) -> list[dict[str, str]]:
    """Parse an uploaded CSV (UTF-8, header row). Column names are matched case-insensitively."""
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV is larger than 1 MB")
    if data[:2] == b"PK":  # an Excel workbook (.xlsx is a zip file): read its first sheet as rows
        from backend.xlsx_read import read_xlsx_rows
        sheet_rows = read_xlsx_rows(data)
        buf = io.StringIO()
        csv.writer(buf).writerows(sheet_rows)
        data = buf.getvalue().encode("utf-8")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=422, detail="Save the CSV as UTF-8 and try again") from e
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="The CSV is empty")
    present = {(f or "").strip().lower() for f in reader.fieldnames}
    missing = [c for c in columns if c not in present and c not in ("skills", "tags", "subcategory", "content_owner", "source_url", *optional)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing column(s): {', '.join(missing)}. Download the template to see the format.")
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]
    rows = [r for r in rows if any(r.values())]
    if not rows:
        raise HTTPException(status_code=422, detail="The CSV has a header but no rows")
    if len(rows) > 200:
        raise HTTPException(status_code=422, detail="Upload at most 200 rows at a time")
    return rows


@router.post("/connect/bulk")
async def connect_bulk(file: UploadFile = File(...), dry_run: bool = Form(True),
                       user: dict = Depends(need("connect.manage"))) -> dict[str, Any]:
    """Add many Connect profiles from one CSV. dry_run=true checks every row and saves nothing."""
    rows = read_csv_upload(await file.read(MAX_CSV_BYTES + 1), CONNECT_CSV_COLUMNS, optional=("website",))
    checked, valid = [], []
    for n, r in enumerate(rows, start=2):
        errors = []
        try:
            item = ConnectIn(network_group=r.get("network_group", ""), subcategory=r.get("subcategory", ""),
                             display_name=r.get("display_name", ""), role_title=r.get("role_title", ""),
                             organization=r.get("organization", ""), about=r.get("about", ""),
                             skills=[s for s in re.split(r"[;|]", r.get("skills", "")) if s.strip()][:8],
                             website=r.get("website", ""))
            if item.network_group not in CONNECT_GROUPS:
                errors.append("network_group must be one of: " + ", ".join(CONNECT_GROUPS))
            try:
                _clean_site(item.website)
            except HTTPException as bad:
                errors.append(f"website: {bad.detail}")
        except ValidationError as err:
            item = None
            errors.extend(f"{e['loc'][0] if e['loc'] else 'row'}: {e['msg']}" for e in err.errors())
        checked.append({"row": n, "name": r.get("display_name", ""), "group": r.get("network_group", ""), "errors": errors})
        if item and not errors:
            valid.append(item)
    if dry_run or any(c["errors"] for c in checked):
        return {"saved": 0, "rows": checked, "ok": not any(c["errors"] for c in checked)}
    approval = _initial_approval(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            for item in valid:
                _insert_connect(cur, user, item, approval)
            _audit(cur, user, "connect.bulk", f"{len(valid)} profiles", {"approval": approval})
        conn.commit()
    return {"saved": len(valid), "rows": checked, "ok": True, "approval": approval}


# ---------------------------------------------------------------- approvals (Super Admin)
APPROVAL_TABLES = {"event": ("events", "title"), "connect": ("connect_entries", "display_name"), "update": ("sector_updates", "title")}


class ApprovalIn(BaseModel):
    action: str  # approve | return
    comment: str | None = Field(default=None, max_length=600)


@router.get("/approvals")
def list_approvals(user: dict = Depends(need("content.approve"))) -> dict[str, Any]:
    """Everything waiting for the Super Admin, oldest first. Resources are approved in Content review."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 'resource', r.id, r.title, r.category || COALESCE(' · ' || r.subcategory, ''), r.submitted_by,
                       r.updated_at, c.name, r.review_note, r.description, r.source_url
                FROM resources r LEFT JOIN companies c ON c.id = r.company_id WHERE r.status = 'in_review'
                UNION ALL
                SELECT 'resource_edit', r.id, r.title, 'Edit to a published resource (the current version stays live)', r.pending_by,
                       r.pending_at, c.name, CASE WHEN r.pending_file IS NOT NULL THEN 'New file attached' END, r.pending_changes, NULL
                FROM resources r LEFT JOIN companies c ON c.id = r.company_id
                WHERE r.status = 'approved' AND (r.pending_changes IS NOT NULL OR r.pending_file IS NOT NULL)
                UNION ALL
                SELECT 'event', e.id, e.title, e.location || ' · ' || to_char((e.starts_at AT TIME ZONE 'UTC') + INTERVAL '330 minutes', 'DD Mon YYYY, HH12:MI am') || ' IST',
                       e.created_by, e.created_at, COALESCE(c.name, 'All founders'), e.join_link, e.description, NULL
                FROM events e LEFT JOIN companies c ON c.id = e.company_id WHERE e.approval = 'pending'
                UNION ALL
                SELECT 'event_link', e.id, e.title, 'New join link', e.pending_link_by, e.pending_link_at,
                       COALESCE(c.name, 'All founders'), e.pending_join_link, 'Current link: ' || COALESCE(e.join_link, 'none'), NULL
                FROM events e LEFT JOIN companies c ON c.id = e.company_id WHERE e.pending_join_link IS NOT NULL
                UNION ALL
                SELECT 'event_recording', e.id, e.title, 'New recording link', e.pending_recording_by, e.pending_recording_at,
                       COALESCE(c.name, 'All founders'), e.pending_recording_url, NULL, e.pending_recording_url
                FROM events e LEFT JOIN companies c ON c.id = e.company_id WHERE e.pending_recording_url IS NOT NULL
                UNION ALL
                SELECT 'connect', e.id, e.display_name, e.network_group || ' · ' || e.subcategory, e.created_by, e.created_at,
                       NULL, e.organization, e.role_title || ' · ' || COALESCE(e.why_relevant, ''), NULL
                FROM connect_entries e WHERE e.approval = 'pending'
                UNION ALL
                SELECT 'update', s.id, s.title, s.label || ' · ' || s.source, s.published_by, s.published_at, c.name, s.label,
                       s.summary, s.source_url
                FROM sector_updates s LEFT JOIN companies c ON c.id = s.company_id
                WHERE s.approval = 'pending' AND (s.expires_at IS NULL OR s.expires_at > NOW())
                ORDER BY 6
                """
            )
            rows = cur.fetchall()
    kinds = {"resource": "Resource", "resource_edit": "Resource edit", "event": "Event", "event_link": "Event join link", "event_recording": "Event recording",
             "connect": "Connect profile", "update": "Sector update"}
    return {"items": [
        {"kind": r[0], "kind_label": kinds[r[0]], "id": r[1], "title": r[2], "detail": r[3], "submitted_by": r[4],
         "submitted_at": iso(r[5]), "company": r[6], "extra": r[7], "body": r[8], "link": r[9]}
        for r in rows
    ]}


@router.post("/approvals/{kind}/{item_id}")
def decide_approval(kind: str, item_id: int, body: ApprovalIn, user: dict = Depends(need("content.approve"))) -> dict[str, str]:
    if kind == "resource_edit":
        return _decide_resource_edit(item_id, body, user)
    if kind in ("event_link", "event_recording"):
        return _decide_event_link(item_id, body, user, "recording_url" if kind == "event_recording" else "join_link")
    if kind not in APPROVAL_TABLES:
        raise HTTPException(status_code=422, detail="Approve resources in Content review")
    if body.action not in ("approve", "return"):
        raise HTTPException(status_code=422, detail="action must be approve or return")
    if body.action == "return" and not (body.comment or "").strip():
        raise HTTPException(status_code=422, detail="Say what should change when returning an item")
    table, title_col = APPROVAL_TABLES[kind]
    status = "approved" if body.action == "approve" else "returned"
    with get_conn() as conn:
        with conn.cursor() as cur:
            company = "company_id" if kind != "connect" else "NULL::int"
            # A returned item can still be approved later; nothing is decided twice.
            allowed_from = "('pending', 'returned')" if body.action == "approve" else "('pending')"
            cur.execute(  # table and column names come from the fixed map above
                f"UPDATE {table} SET approval = %s, review_note = %s, reviewed_by = %s WHERE id = %s AND approval IN {allowed_from} "
                f"RETURNING {title_col}, {company}",
                (status, (body.comment or "").strip() or None, user["full_name"], item_id),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(f"SELECT 1 FROM {table} WHERE id = %s", (item_id,))
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="This item has already been decided")
                raise HTTPException(status_code=404, detail="Item not found")
            _audit(cur, user, f"approval.{body.action}", row[0], {"kind": kind, "comment": body.comment}, row[1])
        conn.commit()
    return {"status": status}


RESOURCE_EDIT_FIELDS = ("title", "description", "category", "subcategory", "content_owner", "source_url", "tags",
                        "company_id", "is_portfolio_wide", "target_company_ids", "target_sectors", "target_stages")


def _decide_resource_edit(resource_id: int, body: ApprovalIn, user: dict[str, Any]) -> dict[str, str]:
    """Apply an edit to a published resource (details and/or a new file), or return it with a note."""
    if body.action not in ("approve", "return"):
        raise HTTPException(status_code=422, detail="action must be approve or return")
    if body.action == "return" and not (body.comment or "").strip():
        raise HTTPException(status_code=422, detail="Say what should change when returning an item")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, company_id, pending_changes, pending_file FROM resources WHERE id = %s", (resource_id,))
            row = cur.fetchone()
            if not row or not (row[2] or row[3]):
                raise HTTPException(status_code=404, detail="No edit is waiting for this resource")
            title, company_id, changes, new_file = row
            if body.action == "approve":
                for col, val in json.loads(changes or "{}").items():
                    if col in RESOURCE_EDIT_FIELDS:  # only known columns
                        keep = isinstance(val, (list, bool, int))  # audience values keep their type ([] stays [])
                        cur.execute(f"UPDATE resources SET {col} = %s WHERE id = %s", (val if keep else (val or None), resource_id))
                if new_file:
                    ext = new_file.rsplit(".", 1)[-1].upper()
                    cur.execute("UPDATE resources SET file_name = %s, resource_type = %s WHERE id = %s", (new_file, ext, resource_id))
                note = "Approved by Demo Ventures at content review"
                cur.execute("UPDATE resources SET review_note = %s, reviewed_by = %s, reviewed_at = NOW() WHERE id = %s",
                            (note, user["full_name"], resource_id))
            else:
                cur.execute("UPDATE resources SET review_comment = %s WHERE id = %s", (body.comment.strip(), resource_id))
            cur.execute("UPDATE resources SET pending_changes = NULL, pending_file = NULL, pending_by = NULL, pending_at = NULL, "
                        "updated_at = NOW() WHERE id = %s", (resource_id,))
            _audit(cur, user, f"approval.{body.action}", title, {"kind": "resource_edit", "comment": body.comment}, company_id)
        conn.commit()
    return {"status": "approved" if body.action == "approve" else "returned"}


EVENT_PENDING = {  # live column -> (waiting value, who, when)
    "join_link": ("pending_join_link", "pending_link_by", "pending_link_at"),
    "recording_url": ("pending_recording_url", "pending_recording_by", "pending_recording_at"),
}


def _decide_event_link(event_id: int, body: ApprovalIn, user: dict[str, Any], field: str = "join_link") -> dict[str, str]:
    """Approve a new join or recording link (it replaces the current one) or return it with a note."""
    if body.action not in ("approve", "return"):
        raise HTTPException(status_code=422, detail="action must be approve or return")
    if body.action == "return" and not (body.comment or "").strip():
        raise HTTPException(status_code=422, detail="Say what should change when returning an item")
    pend, by, at = EVENT_PENDING[field]
    with get_conn() as conn:
        with conn.cursor() as cur:  # column names come from the fixed map above
            cur.execute(f"SELECT title, company_id, {pend} FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
            if not row or not row[2]:
                raise HTTPException(status_code=404, detail="No link is waiting for this event")
            if body.action == "approve":
                cur.execute(f"UPDATE events SET {field} = {pend}, {pend} = NULL, {by} = NULL, {at} = NULL, review_note = NULL "
                            "WHERE id = %s", (event_id,))
            else:
                cur.execute(f"UPDATE events SET {pend} = NULL, {by} = NULL, {at} = NULL, review_note = %s WHERE id = %s",
                            (body.comment.strip(), event_id))
            _audit(cur, user, f"approval.{body.action}", row[0], {"kind": field, "link": row[2], "comment": body.comment}, row[1])
        conn.commit()
    return {"status": "approved" if body.action == "approve" else "returned"}


# ---------------------------------------------------------------- team: Super Admin, Admins, Analysts
class HandoverIn(BaseModel):
    email: EmailStr
    confirm_email: EmailStr
    full_name: str | None = Field(default=None, min_length=2, max_length=120)  # needed only for a new account


class LevelIn(BaseModel):
    level: str  # admin | analyst


class ReportsToIn(BaseModel):
    manager_id: int | None = None  # the Admin an Analyst reports to; None = reports to the Super Admin directly


def _holds_super_admin(cur, user_id: int) -> bool:
    cur.execute("SELECT 1 FROM user_roles WHERE user_id = %s AND role_code = %s", (user_id, SUPER_ADMIN))
    return cur.fetchone() is not None


@router.get("/roles")
def list_roles(user: dict = Depends(need("staff.manage", "admins.manage", "super_admin.handover"))) -> list[dict[str, Any]]:
    """The three tiers and what each one allows, in plain language (shown in Team & access)."""
    return [
        {"code": code, "name": name, "tier": tier,
         "permissions": [{"code": p, "label": PERMISSIONS[p][0], "description": PERMISSIONS[p][1],
                          "assigned_only": sc == "assigned"} for p, sc in grants.items()]}
        for code, (name, staff, tier, grants) in sorted(ROLES.items(), key=lambda kv: kv[1][2]) if staff
    ]


@router.get("/team")
def list_team(user: dict = Depends(need("staff.manage", "admins.manage", "super_admin.handover"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.full_name, u.email, u.active, u.created_at, u.last_login_at,
                    ARRAY(SELECT r.role_code FROM user_roles r WHERE r.user_id = u.id ORDER BY r.role_code),
                    ARRAY(SELECT DISTINCT c.name FROM (SELECT DISTINCT ON (company_id, role) company_id, user_id
                            FROM company_assignments ORDER BY company_id, role, effective_from DESC, id DESC) a
                          JOIN companies c ON c.id = a.company_id WHERE a.user_id = u.id),
                    u.reports_to, m.full_name
                FROM users u LEFT JOIN users m ON m.id = u.reports_to
                WHERE u.account_type = 'staff' ORDER BY u.active DESC, u.full_name
                """
            )
            rows = cur.fetchall()
            manageable = set()
            for r in rows:  # the same rule the account actions enforce, so the page shows only buttons that work
                if r[0] == user["id"]:
                    continue
                try:
                    _can_manage_staff(cur, user, r[0])
                    manageable.add(r[0])
                except HTTPException:
                    pass
    return [
        {"id": r[0], "full_name": r[1], "email": r[2], "active": r[3], "created_at": iso(r[4]),
         "last_sign_in": iso(r[5]), "roles": list(r[6] or []), "companies": sorted(r[7] or []), "is_you": r[0] == user["id"],
         "reports_to": r[8], "reports_to_name": r[9], "can_manage": r[0] in manageable}
        for r in rows
    ]


@router.post("/team")
def add_team_member(body: StaffIn, user: dict = Depends(need("staff.manage", "admins.manage"))) -> dict[str, Any]:
    """Add an Analyst (Admins and the Super Admin) or an Admin (Super Admin only). The Super Admin
    role is only ever handed over."""
    if body.level not in STAFF_LEVELS:
        raise HTTPException(status_code=422, detail="Tier must be admin or analyst")
    require_perm(user, "admins.manage" if body.level == "admin" else "staff.manage")
    email = body.email.lower()
    temp, pw_hash = _temp_password()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="This email already has an account")
            cur.execute(
                "INSERT INTO users (email, password_hash, full_name, account_type, company_id) "
                "VALUES (%s, %s, %s, 'staff', NULL) RETURNING id",
                (email, pw_hash, body.full_name.strip()),
            )
            uid = cur.fetchone()[0]
            cur.execute("INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, %s, %s)", (uid, body.level, user["email"]))
            if body.level == "analyst" and not has_perm(user, "admins.manage"):
                cur.execute("UPDATE users SET reports_to = %s WHERE id = %s", (user["id"], uid))  # an Admin's new analyst reports to them
            _audit(cur, user, "team.invite", email, {"tier": body.level})
        conn.commit()
    return {"id": uid, "email": email, "roles": [body.level], "temporary_password": temp}


@router.put("/team/{user_id}/level")
def change_level(user_id: int, body: LevelIn, user: dict = Depends(need("admins.manage"))) -> dict[str, Any]:
    """Move a staff member between the Admin and Analyst tiers (Super Admin only)."""
    if body.level not in STAFF_LEVELS:
        raise HTTPException(status_code=422, detail="Tier must be admin or analyst")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email, account_type FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            if row[1] != "staff":
                raise HTTPException(status_code=422, detail="Founders have no staff tier")
            if _holds_super_admin(cur, user_id):
                raise HTTPException(status_code=422, detail="The Super Admin role moves only with the hand-over")
            before = _staff_tier(cur, user_id)
            cur.execute("DELETE FROM user_roles WHERE user_id = %s", (user_id,))
            cur.execute("INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, %s, %s)", (user_id, body.level, user["email"]))
            if before != body.level:
                _audit(cur, user, "team.level", row[0], {"before": before, "after": body.level})
                if body.level == "admin":  # Admins report to the Super Admin
                    cur.execute("UPDATE users SET reports_to = NULL WHERE id = %s", (user_id,))
                else:  # their analysts now report to the Super Admin until reassigned
                    cur.execute("UPDATE users SET reports_to = NULL WHERE reports_to = %s", (user_id,))
        conn.commit()
    return {"status": "updated", "level": body.level}


@router.put("/team/{user_id}/reports-to")
def change_reports_to(user_id: int, body: ReportsToIn, user: dict = Depends(need("admins.manage"))) -> dict[str, Any]:
    """Choose the Admin an Analyst reports to (Super Admin only)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if _staff_tier(cur, user_id) != "analyst":
                raise HTTPException(status_code=422, detail="Only analysts report to an Admin")
            manager_name = None
            if body.manager_id is not None:
                if _staff_tier(cur, body.manager_id) != "admin":
                    raise HTTPException(status_code=422, detail="Choose an Admin")
                cur.execute("SELECT full_name FROM users WHERE id = %s", (body.manager_id,))
                manager_name = cur.fetchone()[0]
            cur.execute("UPDATE users SET reports_to = %s WHERE id = %s RETURNING email", (body.manager_id, user_id))
            email = cur.fetchone()[0]
            _audit(cur, user, "team.reports_to", email, {"reports_to": manager_name or "Super Admin"})
        conn.commit()
    return {"status": "updated", "reports_to": body.manager_id}


@router.post("/super-admin/handover")
def hand_over_super_admin(body: HandoverIn, user: dict = Depends(need("super_admin.handover"))) -> dict[str, Any]:
    """Move the one Super Admin role to another person (an existing staff member, or a new account).
    The current Super Admin becomes an Analyst. Typing the email twice guards against mistakes."""
    email, confirm = body.email.lower(), body.confirm_email.lower()
    if email != confirm:
        raise HTTPException(status_code=422, detail="The two email addresses do not match")
    if email == user["email"].lower():
        raise HTTPException(status_code=422, detail="You are already the Super Admin")
    temp = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            if not _holds_super_admin(cur, user["id"]):
                raise HTTPException(status_code=403, detail="Only the current Super Admin can hand the role over")
            cur.execute("SELECT id, account_type, active, full_name FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                target_id, account_type, active, target_name = row
                if account_type != "staff":
                    raise HTTPException(status_code=422, detail="A founder account cannot be the Super Admin")
                if not active:
                    raise HTTPException(status_code=422, detail="That account is deactivated. Reactivate it first.")
            else:
                if not body.full_name:
                    raise HTTPException(status_code=422, detail="This email has no account yet. Add the person's full name to create one.")
                temp, pw_hash = _temp_password()
                cur.execute(
                    "INSERT INTO users (email, password_hash, full_name, account_type) VALUES (%s, %s, %s, 'staff') RETURNING id",
                    (email, pw_hash, body.full_name.strip()),
                )
                target_id, target_name = cur.fetchone()[0], body.full_name.strip()
            # Order matters: the database allows only one Super Admin at a time.
            cur.execute("DELETE FROM user_roles WHERE user_id = %s AND role_code = %s", (user["id"], SUPER_ADMIN))
            cur.execute(
                "INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'analyst', %s) ON CONFLICT DO NOTHING",
                (user["id"], "super-admin hand-over"),
            )
            cur.execute("DELETE FROM user_roles WHERE user_id = %s", (target_id,))
            cur.execute(
                "INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, %s, %s)",
                (target_id, SUPER_ADMIN, user["email"]),
            )
            _audit(cur, user, "super_admin.handover", email, {"from": user["email"], "to": email, "new_account": temp is not None})
        conn.commit()
    return {"status": "handed_over", "super_admin": {"email": email, "full_name": target_name}, "temporary_password": temp}


# ---------------------------------------------------------------- audit trail (changes + downloads)
def _audit_rows(cur, user: dict[str, Any], kind: str = "all", limit: int = 300) -> list[dict[str, Any]]:
    """Admin changes and resource downloads, newest first. The Super Admin sees everything; an Admin
    sees only entries for their own companies."""
    allowed = company_scope(user, "audit.view")
    ids = list(allowed) if allowed is not None else None
    rows: list[tuple] = []
    if kind in ("all", "changes"):
        cur.execute(
            """
            SELECT a.created_at, a.actor, COALESCE(u.full_name, a.actor), a.action, a.target, c.name, a.details
            FROM admin_audit a LEFT JOIN users u ON lower(u.email) = lower(a.actor) LEFT JOIN companies c ON c.id = a.company_id
            WHERE (%s::int[] IS NULL OR a.company_id = ANY(%s::int[]))
            ORDER BY a.created_at DESC LIMIT %s
            """,
            (ids, ids, limit),
        )
        rows += cur.fetchall()
    if kind in ("all", "downloads"):
        cur.execute(
            """
            SELECT d.created_at, u.email, u.full_name, 'resource.download', r.title, c.name, NULL
            FROM resource_downloads d JOIN users u ON u.id = d.user_id JOIN resources r ON r.id = d.resource_id
            LEFT JOIN companies c ON c.id = d.company_id
            WHERE (%s::int[] IS NULL OR d.company_id = ANY(%s::int[]))
            ORDER BY d.created_at DESC LIMIT %s
            """,
            (ids, ids, limit),
        )
        rows += cur.fetchall()
    rows.sort(key=lambda r: r[0], reverse=True)
    return [
        {"at": iso(r[0]), "actor": r[1], "actor_name": r[2], "action": r[3], "what": action_label(r[3]), "target": r[4],
         "company": r[5], "details": r[6]}
        for r in rows[:limit]
    ]


@router.get("/audit")
def audit_log(kind: str = "all", user: dict = Depends(need("audit.view"))) -> list[dict[str, Any]]:
    if kind not in ("all", "changes", "downloads"):
        raise HTTPException(status_code=422, detail="kind must be all, changes or downloads")
    with get_conn() as conn:
        with conn.cursor() as cur:
            return _audit_rows(cur, user, kind)


# ---------------------------------------------------------------- activity tracker
ACTIVITY_KINDS = {"founder": "activity.founders", "analyst": "activity.analysts", "admin": "activity.admins"}


@router.get("/activity")
def activity_people(kind: str = "founder", user: dict = Depends(need(*ACTIVITY_KINDS.values()))) -> list[dict[str, Any]]:
    """People whose activity the user may track, with a 30-day summary.
    Founders: all three tiers (their companies). Analysts: Admins and the Super Admin. Admins: Super Admin only."""
    if kind not in ACTIVITY_KINDS:
        raise HTTPException(status_code=422, detail="kind must be founder, analyst or admin")
    perm = ACTIVITY_KINDS[kind]
    require_perm(user, perm)
    with get_conn() as conn:
        with conn.cursor() as cur:
            if kind == "founder":
                allowed = company_scope(user, perm)
                ids = list(allowed) if allowed is not None else None
                cur.execute(
                    """
                    SELECT u.id, u.full_name, u.email, c.name, u.active, u.last_login_at,
                        (SELECT COUNT(*) FROM sign_ins s WHERE s.user_id = u.id AND s.created_at > NOW() - INTERVAL '30 days'),
                        (SELECT COUNT(*) FROM resource_downloads d WHERE d.user_id = u.id),
                        (SELECT COUNT(*) FROM founder_help h WHERE h.user_id = u.id),
                        EXISTS (SELECT 1 FROM founder_intake i WHERE i.user_id = u.id)
                    FROM users u JOIN companies c ON c.id = u.company_id
                    WHERE u.account_type = 'founder' AND (%s::int[] IS NULL OR u.company_id = ANY(%s::int[]))
                    ORDER BY c.name, u.full_name
                    """,
                    (ids, ids),
                )
                return [
                    {"id": r[0], "full_name": r[1], "email": r[2], "company": r[3], "active": r[4], "last_sign_in": iso(r[5]),
                     "sign_ins_30d": r[6], "downloads": r[7], "requests": r[8], "questionnaire_done": r[9]}
                    for r in cur.fetchall()
                ]
            people = colleague_ids(user, perm)
            ids = list(people) if people is not None else None
            cur.execute(
                """
                SELECT u.id, u.full_name, u.email, u.active, u.last_login_at,
                    (SELECT COUNT(*) FROM sign_ins s WHERE s.user_id = u.id AND s.created_at > NOW() - INTERVAL '30 days'),
                    (SELECT COUNT(*) FROM admin_audit a WHERE lower(a.actor) = lower(u.email) AND a.created_at > NOW() - INTERVAL '30 days'),
                    ARRAY(SELECT DISTINCT c.name FROM (SELECT DISTINCT ON (company_id, role) company_id, user_id
                            FROM company_assignments ORDER BY company_id, role, effective_from DESC, id DESC) a
                          JOIN companies c ON c.id = a.company_id WHERE a.user_id = u.id)
                FROM users u JOIN user_roles r ON r.user_id = u.id AND r.role_code = %s
                WHERE u.account_type = 'staff' AND (%s::int[] IS NULL OR u.id = ANY(%s::int[]))
                ORDER BY u.full_name
                """,
                (kind, ids, ids),
            )
            return [
                {"id": r[0], "full_name": r[1], "email": r[2], "active": r[3], "last_sign_in": iso(r[4]),
                 "sign_ins_30d": r[5], "actions_30d": r[6], "companies": sorted(r[7] or [])}
                for r in cur.fetchall()
            ]


def person_timeline(cur, person_id: int, limit: int = 80) -> list[dict[str, Any]]:
    """Everything one person did, newest first (sign-ins, downloads, requests, questionnaire, RSVPs,
    playbook ticks, admin actions)."""
    cur.execute("SELECT email, full_name, company_id FROM users WHERE id = %s", (person_id,))
    email, name, company_id = cur.fetchone()
    cur.execute(
        """
        SELECT * FROM (
            SELECT s.created_at AS at, 'auth.sign_in' AS action, '' AS target FROM sign_ins s WHERE s.user_id = %(id)s
            UNION ALL SELECT d.created_at, 'resource.download', r.title FROM resource_downloads d
                JOIN resources r ON r.id = d.resource_id WHERE d.user_id = %(id)s
            UNION ALL SELECT h.created_at, 'founder.request', h.subject FROM founder_help h WHERE h.user_id = %(id)s
            UNION ALL SELECT i.created_at, 'founder.questionnaire', 'Questionnaire answered' FROM founder_intake i WHERE i.user_id = %(id)s
            UNION ALL SELECT v.created_at, 'founder.rsvp', e.title FROM event_rsvps v JOIN events e ON e.id = v.event_id WHERE v.user_id = %(id)s
            UNION ALL SELECT t.done_at, 'founder.task_done', t.title FROM playbook_tasks t
                WHERE t.done AND t.done_at IS NOT NULL AND t.done_by = %(name)s AND t.company_id = %(cid)s
            UNION ALL SELECT a.created_at, a.action, a.target FROM admin_audit a WHERE lower(a.actor) = lower(%(email)s)
        ) x ORDER BY at DESC LIMIT %(limit)s
        """,
        {"id": person_id, "name": name, "cid": company_id, "email": email, "limit": limit},
    )
    extra = {"founder.request": "Asked Demo Ventures for help", "founder.questionnaire": "Answered the questionnaire",
             "founder.rsvp": "RSVP'd to an event", "founder.task_done": "Completed a playbook task"}
    return [{"at": iso(r[0]), "action": r[1], "what": extra.get(r[1]) or action_label(r[1]), "target": r[2]} for r in cur.fetchall()]


@router.get("/activity/{person_id}")
def activity_detail(person_id: int, user: dict = Depends(need(*ACTIVITY_KINDS.values()))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT full_name, email, account_type, company_id FROM users WHERE id = %s", (person_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Person not found")
            name, email, account_type, company_id = row
            if account_type == "founder":
                require_company(user, "activity.founders", company_id)
                kind = "founder"
            else:
                kind = _staff_tier(cur, person_id) or "analyst"
                if kind == SUPER_ADMIN:
                    raise HTTPException(status_code=403, detail="The Super Admin's activity is in the audit trail")
                perm = ACTIVITY_KINDS[kind]
                require_perm(user, perm)
                people = colleague_ids(user, perm)
                if people is not None and person_id not in people:
                    raise HTTPException(status_code=403, detail="This person works on other companies")
            return {"person": {"id": person_id, "full_name": name, "email": email, "kind": kind}, "timeline": person_timeline(cur, person_id)}


CompanyIn.model_rebuild()  # resolves the FounderIn forward reference
