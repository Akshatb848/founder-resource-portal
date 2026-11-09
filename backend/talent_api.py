"""Hiring: open roles, candidate interest, and candidate profiles featured for a company's founders.

Manager request (25 Oct 2026) and meeting 1 (26 Oct 2026):
- An analyst who finds a candidate fitting an opening features the profile for that company. Any Admin (or the
  Super Admin) decides whether it is good enough before founders see it; an Admin's or the Super Admin's own
  profile is shown at once. Approved profiles appear at the top of the founders' dashboard and on Hiring.
- The founder answers "Interested" (this opens a normal Demo Ventures support request, so the introduction is tracked
  in the one request system) or "Not a fit".
- Each opening can have a shareable interest link. Candidates register interest there (with consent); Demo Ventures
  screens it, and a suitable candidate becomes a profile in one click, so nothing is typed twice.
- Profiles can also be uploaded in bulk from a CSV.

    Founder:  GET /api/founder/hiring · POST /api/founder/hiring/roles · PATCH /api/founder/hiring/roles/{id}
              POST /api/founder/hiring/roles/{id}/link · POST /api/founder/hiring/profiles/{id}/respond
    Demo Ventures: GET /api/analyst/hiring · POST /api/analyst/hiring/roles · PATCH /api/analyst/hiring/roles/{id}
              POST /api/analyst/hiring/roles/{id}/link · POST /api/analyst/hiring/profiles
              PATCH /api/analyst/hiring/profiles/{id} · POST /api/analyst/hiring/profiles/{id}/review
              POST /api/analyst/hiring/interest/{id}/decline
              GET /api/analyst/hiring/profiles/bulk-template · POST /api/analyst/hiring/profiles/bulk
    Public:   GET /api/public/opening/{token} · POST /api/public/opening/{token}/interest
"""
from __future__ import annotations

import csv
import io
import secrets
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, ValidationError

from backend.admin_api import _audit, read_csv_upload
from backend.config import PORTAL_URL
from backend.db import get_conn
from backend.messaging import company_founders, company_team, deliver_later, notify, portal_link, workspace_link
from backend.security import (
    auth_session,
    company_scope,
    founder_company,
    has_perm,
    iso,
    need,
    require_company,
    require_founder,
    require_founder_or_preview,
)

router = APIRouter(prefix="/api")

SENIORITY = ("Mid-level", "Senior", "Leadership", "CXO")
ROLE_STATUS_LABEL = {"open": "Open", "filled": "Filled", "closed": "Closed"}
PROFILE_STATUS_LABEL = {
    "featured": "Waiting for your reply",
    "interested": "Introduction requested",
    "not_fit": "Not a fit",
    "withdrawn": "Withdrawn by Demo Ventures",
}
APPROVAL_LABEL = {"pending": "Waiting for an Admin's approval", "approved": "Approved", "returned": "Returned for changes"}


class RoleIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    seniority: str = "Senior"
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=600)


class StaffRoleIn(RoleIn):
    company_id: int


class RoleStatusIn(BaseModel):
    status: Literal["open", "filled", "closed"]


class LinkIn(BaseModel):
    on: bool = True


class ProfileFields(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    headline: str = Field(min_length=3, max_length=160)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    location: str | None = Field(default=None, max_length=120)
    summary: str = Field(min_length=10, max_length=1200)
    fit_note: str = Field(min_length=10, max_length=600)
    profile_url: str | None = Field(default=None, max_length=300)


class ProfileIn(ProfileFields):
    company_id: int
    role_id: int | None = None
    consent_confirmed: bool = False
    interest_id: int | None = None  # featuring a candidate who registered interest


class ProfilePatch(BaseModel):
    status: Literal["featured", "withdrawn"] | None = None
    headline: str | None = Field(default=None, min_length=3, max_length=160)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    location: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, min_length=10, max_length=1200)
    fit_note: str | None = Field(default=None, min_length=10, max_length=600)
    profile_url: str | None = Field(default=None, max_length=300)


class ReviewIn(BaseModel):
    action: Literal["approve", "return"]
    note: str | None = Field(default=None, max_length=600)


class RespondIn(BaseModel):
    decision: Literal["interested", "not_fit"]
    note: str | None = Field(default=None, max_length=600)


class InterestIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    headline: str = Field(min_length=3, max_length=160)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    location: str | None = Field(default=None, max_length=120)
    profile_url: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=1200)
    consent: bool = False
    website: str | None = Field(default=None, max_length=200)  # hidden field: people leave it empty, bots fill it


def _clean(text: str | None) -> str | None:
    text = (text or "").strip()
    return text or None


def _https(url: str | None) -> str | None:
    url = _clean(url)
    if url and not url.lower().startswith("https://"):
        raise HTTPException(status_code=422, detail="The profile link must start with https://")
    return url


def _check_role(body: RoleIn) -> None:
    if body.seniority not in SENIORITY:
        raise HTTPException(status_code=422, detail=f"Seniority must be one of {', '.join(SENIORITY)}")


def _interest_link(token: str | None) -> str | None:
    return f"{PORTAL_URL}/careers.html?r={token}" if token else None


ROLE_COLS = """r.id, r.company_id, r.title, r.seniority, r.location, r.notes, r.status, r.created_by_name, r.from_fund,
    r.is_sample, r.created_at, r.public_token,
    (SELECT COUNT(*) FROM candidate_interest i WHERE i.role_id = r.id),
    (SELECT COUNT(*) FROM candidate_interest i WHERE i.role_id = r.id AND i.status = 'new')"""


def _role_row(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0], "company_id": r[1], "title": r[2], "seniority": r[3], "location": r[4], "notes": r[5],
        "status": r[6], "status_label": ROLE_STATUS_LABEL.get(r[6], r[6]), "added_by": r[7],
        "from_fund": r[8], "is_sample": r[9], "created_at": iso(r[10]), "interest_link": _interest_link(r[11]),
        "interest_count": r[12], "interest_new": r[13],
    }


PROFILE_COLS = """p.id, p.company_id, p.role_id, r.title, p.full_name, p.headline, p.experience_years, p.location,
    p.summary, p.fit_note, p.profile_url, p.status, p.founder_note, p.featured_by_name, p.featured_at,
    p.responded_by_name, p.responded_at, p.is_sample, h.public_ref, c.name, p.consent_confirmed,
    p.approval, p.review_note, p.reviewed_by, p.source, r.seniority, r.location, r.notes"""
PROFILE_FROM = """talent_profiles p LEFT JOIN hiring_roles r ON r.id = p.role_id
    LEFT JOIN founder_help h ON h.id = p.help_id JOIN companies c ON c.id = p.company_id"""


def _profile_row(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0], "company_id": r[1], "role_id": r[2], "role_title": r[3], "full_name": r[4], "headline": r[5],
        "experience_years": r[6], "location": r[7], "summary": r[8], "fit_note": r[9], "profile_url": r[10],
        "status": r[11], "status_label": PROFILE_STATUS_LABEL.get(r[11], r[11]), "founder_note": r[12],
        "featured_by": r[13], "featured_at": iso(r[14]), "responded_by": r[15], "responded_at": iso(r[16]),
        "is_sample": r[17], "request_ref": r[18], "company_name": r[19], "consent_confirmed": r[20],
        "approval": r[21], "approval_label": APPROVAL_LABEL.get(r[21], r[21]), "review_note": r[22], "reviewed_by": r[23],
        "source": r[24], "role_seniority": r[25], "role_location": r[26], "role_notes": r[27],
    }


INTEREST_COLS = """i.id, i.role_id, r.title, i.company_id, c.name, i.full_name, i.email, i.phone, i.headline,
    i.experience_years, i.location, i.profile_url, i.note, i.status, i.created_at, i.handled_by"""


def _interest_row(r: tuple) -> dict[str, Any]:
    return {"id": r[0], "role_id": r[1], "role_title": r[2], "company_id": r[3], "company_name": r[4], "full_name": r[5],
            "email": r[6], "phone": r[7], "headline": r[8], "experience_years": r[9], "location": r[10],
            "profile_url": r[11], "note": r[12], "status": r[13], "created_at": iso(r[14]), "handled_by": r[15]}


def _insert_role(cur, company_id: int, body: RoleIn, user: dict[str, Any], from_fund: bool) -> int:
    cur.execute(
        """
        INSERT INTO hiring_roles (company_id, title, seniority, location, notes, created_by, created_by_name, from_fund)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (company_id, body.title.strip(), body.seniority, _clean(body.location), _clean(body.notes),
         user["id"], user["full_name"], from_fund),
    )
    return cur.fetchone()[0]


def _set_link(cur, role_id: int, on: bool) -> str | None:
    token = secrets.token_urlsafe(12) if on else None
    if on:
        cur.execute("UPDATE hiring_roles SET public_token = COALESCE(public_token, %s) WHERE id = %s RETURNING public_token",
                    (token, role_id))
        return _interest_link(cur.fetchone()[0])
    cur.execute("UPDATE hiring_roles SET public_token = NULL WHERE id = %s", (role_id,))
    return None


def _tell_founders(cur, profile: dict[str, Any], who: str) -> list[int]:
    """Email the company's founders that an approved candidate is waiting for them."""
    role = f" for your opening {profile['role_title']}" if profile.get("role_title") else ""
    return notify(cur, company_founders(cur, profile["company_id"]), f"A candidate for you from Demo Ventures: {profile['full_name']}"[:200],
                  f"Demo Ventures has a candidate{role}: {profile['full_name']}, {profile['headline']}.\n\n"
                  f"Why we think they fit: {profile['fit_note']}\n\n"
                  f"See the profile and reply (Interested or Not a fit) in the portal: {portal_link('hiring')}",
                  "hiring", who, profile["company_id"])


def _load_profile(cur, profile_id: int) -> dict[str, Any] | None:
    cur.execute(f"SELECT {PROFILE_COLS} FROM {PROFILE_FROM} WHERE p.id = %s", (profile_id,))
    row = cur.fetchone()
    return _profile_row(row) if row else None


# ---------------------------------------------------------------- founder side
@router.get("/founder/hiring")
def founder_hiring(user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder_or_preview(user)
    cid = founder_company(user)[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {ROLE_COLS} FROM hiring_roles r WHERE r.company_id = %s "
                        "ORDER BY (r.status = 'open') DESC, r.created_at DESC", (cid,))
            roles = [_role_row(r) for r in cur.fetchall()]
            cur.execute(
                f"SELECT {PROFILE_COLS} FROM {PROFILE_FROM} WHERE p.company_id = %s AND p.status <> 'withdrawn' "
                "AND p.approval = 'approved' ORDER BY (p.status = 'featured') DESC, p.featured_at DESC",
                (cid,),
            )
            profiles = [_profile_row(r) for r in cur.fetchall()]
    for p in profiles:  # founders see who suggested the profile, not internal review fields
        for k in ("consent_confirmed", "approval", "approval_label", "review_note", "reviewed_by"):
            p.pop(k, None)
    return {"roles": roles, "profiles": profiles,
            "waiting": sum(1 for p in profiles if p["status"] == "featured"), "seniority": list(SENIORITY)}


@router.post("/founder/hiring/roles")
def founder_add_role(body: RoleIn, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder(user)
    _check_role(body)
    with get_conn() as conn:
        with conn.cursor() as cur:
            rid = _insert_role(cur, user["company_id"], body, user, False)
            ids = notify(cur, company_team(cur, user["company_id"]), f"New opening at {user.get('company_name')}: {body.title.strip()}"[:200],
                         f"{user['full_name']} added an opening at {user.get('company_name')}: {body.title.strip()} ({body.seniority}"
                         f"{', ' + body.location.strip() if body.location and body.location.strip() else ''}).\n\n"
                         f"{(body.notes or '').strip()}\n\nLook out for candidates and feature them in Hiring: {workspace_link('hiring')}",
                         "hiring", user["full_name"], user["company_id"])
        conn.commit()
    deliver_later(ids)
    return {"id": rid}


@router.patch("/founder/hiring/roles/{role_id}")
def founder_role_status(role_id: int, body: RoleStatusIn, user: dict = Depends(auth_session)) -> dict[str, str]:
    require_founder(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hiring_roles SET status = %s, updated_at = NOW() WHERE id = %s AND company_id = %s RETURNING id",
                (body.status, role_id, user["company_id"]),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Opening not found")
        conn.commit()
    return {"status": body.status}


@router.post("/founder/hiring/roles/{role_id}/link")
def founder_role_link(role_id: int, body: LinkIn, user: dict = Depends(auth_session)) -> dict[str, Any]:
    """Turn the opening's shareable interest link on or off (for LinkedIn, a careers page or a message)."""
    require_founder(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM hiring_roles WHERE id = %s AND company_id = %s AND status = 'open'", (role_id, user["company_id"]))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Open role not found")
            url = _set_link(cur, role_id, body.on)
        conn.commit()
    return {"interest_link": url}


@router.post("/founder/hiring/profiles/{profile_id}/respond")
def founder_respond(profile_id: int, body: RespondIn, user: dict = Depends(auth_session)) -> dict[str, Any]:
    """Interested opens a support request (category Hiring or HR support) for the Demo Ventures team to arrange
    the conversation. Not a fit closes the suggestion; the optional reason helps Demo Ventures suggest better."""
    require_founder(user)
    note = _clean(body.note)
    alert_ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {PROFILE_COLS} FROM {PROFILE_FROM} WHERE p.id = %s AND p.company_id = %s FOR UPDATE OF p",
                (profile_id, user["company_id"]),
            )
            row = cur.fetchone()
            if not row or row[11] == "withdrawn" or row[21] != "approved":
                raise HTTPException(status_code=404, detail="Profile not found")
            p = _profile_row(row)
            if p["status"] != "featured":
                raise HTTPException(status_code=409, detail="You have already replied to this profile")
            ref = None
            help_id = None
            if body.decision == "interested":
                ref = f"YN-{uuid.uuid4().hex[:6].upper()}"
                role = f" for {p['role_title']}" if p["role_title"] else ""
                context = (f"We would like to speak with {p['full_name']} ({p['headline']}){role}, "
                           f"featured by {p['featured_by']}." + (f" Note from us: {note}" if note else ""))
                cur.execute(
                    """
                    INSERT INTO founder_help (public_ref, company_id, user_id, subject, context, category, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'Hiring or HR support', NOW()) RETURNING id
                    """,
                    (ref, user["company_id"], user["id"], f"Introduction to {p['full_name']}{role}"[:200], context),
                )
                help_id = cur.fetchone()[0]
                cur.execute("INSERT INTO work_items (help_id, internal_status, priority) VALUES (%s, 'queued', 'high')", (help_id,))
            cur.execute(
                """
                UPDATE talent_profiles SET status = %s, founder_note = %s, help_id = %s,
                    responded_by_name = %s, responded_at = NOW() WHERE id = %s
                """,
                (body.decision, note, help_id, user["full_name"], profile_id),
            )
            _audit(cur, user, f"talent.{body.decision}", p["full_name"], {"role": p["role_title"]}, user["company_id"])
            verdict = "would like to meet" if body.decision == "interested" else "said is not a fit for"
            alert_ids = notify(cur, company_team(cur, user["company_id"]),
                               f"{user.get('company_name')}: {p['full_name']}, {'Interested' if body.decision == 'interested' else 'Not a fit'}"[:200],
                               f"{user['full_name']} {verdict} {p['full_name']}" + (f" ({ref})" if ref else "") + "."
                               + (f"\n\nTheir note: {note}" if note else "")
                               + f"\n\n{'Arrange the conversation from Founder requests' if ref else 'See it in Hiring'}: "
                               f"{workspace_link('queue' if ref else 'hiring')}", "hiring", user["full_name"], user["company_id"])
        conn.commit()
    deliver_later(alert_ids)
    return {"status": body.decision, "request_ref": ref}


# ---------------------------------------------------------------- Demo Ventures side
def _staff_scope(user: dict[str, Any]) -> set[int] | None:
    """Admins (talent.approve, all companies) review every company's profiles; analysts see their own."""
    if has_perm(user, "talent.approve") and company_scope(user, "talent.approve") is None:
        return None
    return company_scope(user, "talent.feature")


def _require_hiring_company(user: dict[str, Any], company_id: int) -> None:
    allowed = _staff_scope(user)
    if allowed is not None and company_id not in allowed:
        raise HTTPException(status_code=403, detail="You are not assigned to this company")


@router.get("/analyst/hiring")
def staff_hiring(company_id: int | None = None, user: dict = Depends(need("talent.feature", "talent.approve"))) -> dict[str, Any]:
    allowed = _staff_scope(user)
    if company_id is not None:
        _require_hiring_company(user, company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM companies WHERE status = 'active' ORDER BY name")
            companies = [{"id": r[0], "name": r[1]} for r in cur.fetchall() if allowed is None or r[0] in allowed]
            ids = [c["id"] for c in companies] if company_id is None else [company_id]
            cur.execute(f"SELECT {ROLE_COLS} FROM hiring_roles r WHERE r.company_id = ANY(%s) "
                        "ORDER BY (r.status = 'open') DESC, r.created_at DESC", (ids,))
            roles = [_role_row(r) for r in cur.fetchall()]
            cur.execute(f"SELECT {PROFILE_COLS} FROM {PROFILE_FROM} WHERE p.company_id = ANY(%s) "
                        "ORDER BY (p.approval = 'pending') DESC, p.featured_at DESC", (ids,))
            profiles = [_profile_row(r) for r in cur.fetchall()]
            cur.execute(f"SELECT {INTEREST_COLS} FROM candidate_interest i JOIN hiring_roles r ON r.id = i.role_id "
                        "JOIN companies c ON c.id = i.company_id WHERE i.company_id = ANY(%s) "
                        "ORDER BY (i.status = 'new') DESC, i.created_at DESC LIMIT 300", (ids,))
            interest = [_interest_row(r) for r in cur.fetchall()]
    return {"companies": companies, "roles": roles, "profiles": profiles, "interest": interest,
            "seniority": list(SENIORITY), "can_approve": has_perm(user, "talent.approve"),
            "can_feature": has_perm(user, "talent.feature")}


@router.post("/analyst/hiring/roles")
def staff_add_role(body: StaffRoleIn, user: dict = Depends(need("talent.feature"))) -> dict[str, Any]:
    require_company(user, "talent.feature", body.company_id)
    _check_role(body)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM companies WHERE id = %s", (body.company_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Company not found")
            rid = _insert_role(cur, body.company_id, body, user, True)
            _audit(cur, user, "hiring.role.add", body.title.strip(), {"company": row[0]}, body.company_id)
        conn.commit()
    return {"id": rid}


@router.patch("/analyst/hiring/roles/{role_id}")
def staff_role_status(role_id: int, body: RoleStatusIn, user: dict = Depends(need("talent.feature"))) -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, title FROM hiring_roles WHERE id = %s", (role_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Opening not found")
            require_company(user, "talent.feature", row[0])
            cur.execute("UPDATE hiring_roles SET status = %s, updated_at = NOW() WHERE id = %s", (body.status, role_id))
            if body.status != "open":
                cur.execute("UPDATE hiring_roles SET public_token = NULL WHERE id = %s", (role_id,))
            _audit(cur, user, f"hiring.role.{body.status}", row[1], None, row[0])
        conn.commit()
    return {"status": body.status}


@router.post("/analyst/hiring/roles/{role_id}/link")
def staff_role_link(role_id: int, body: LinkIn, user: dict = Depends(need("talent.feature"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, title, status FROM hiring_roles WHERE id = %s", (role_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Opening not found")
            require_company(user, "talent.feature", row[0])
            if body.on and row[2] != "open":
                raise HTTPException(status_code=422, detail="Only an open role can have an interest link")
            url = _set_link(cur, role_id, body.on)
            _audit(cur, user, "hiring.link.on" if body.on else "hiring.link.off", row[1], None, row[0])
        conn.commit()
    return {"interest_link": url}


def _create_profile(cur, user: dict[str, Any], body: ProfileIn, source: str) -> tuple[int, str]:
    if not body.consent_confirmed:
        raise HTTPException(status_code=422, detail="Confirm that the candidate agreed to share their profile with this company")
    url = _https(body.profile_url)
    cur.execute("SELECT name FROM companies WHERE id = %s AND status = 'active'", (body.company_id,))
    company = cur.fetchone()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if body.role_id is not None:
        cur.execute("SELECT 1 FROM hiring_roles WHERE id = %s AND company_id = %s AND status = 'open'", (body.role_id, body.company_id))
        if not cur.fetchone():
            raise HTTPException(status_code=422, detail="Choose an open role at this company")
    approval = "approved" if has_perm(user, "talent.approve") else "pending"
    cur.execute(
        """
        INSERT INTO talent_profiles (company_id, role_id, full_name, headline, experience_years, location,
            summary, fit_note, profile_url, consent_confirmed, featured_by, featured_by_name, approval, source,
            reviewed_by, reviewed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() END) RETURNING id
        """,
        (body.company_id, body.role_id, body.full_name.strip(), body.headline.strip(), body.experience_years,
         _clean(body.location), body.summary.strip(), body.fit_note.strip(), url, user["id"], user["full_name"],
         approval, source, user["full_name"] if approval == "approved" else None, approval == "approved"),
    )
    pid = cur.fetchone()[0]
    _audit(cur, user, "talent.feature", body.full_name.strip(), {"company": company[0], "approval": approval, "source": source},
           body.company_id)
    return pid, approval


def _ask_admins(cur, profile: dict[str, Any], who: str) -> list[int]:
    """Email every active Admin (and the Super Admin) that a profile waits for approval."""
    cur.execute(
        """
        SELECT DISTINCT u.email, u.full_name, u.phone FROM users u JOIN user_roles r ON r.user_id = u.id
        WHERE u.active AND u.account_type = 'staff' AND r.role_code IN ('admin', 'super_admin')
        """
    )
    return notify(cur, cur.fetchall(), f"Candidate to approve: {profile['full_name']} for {profile['company_name']}"[:200],
                  f"{who} featured {profile['full_name']} ({profile['headline']}) for {profile['company_name']}"
                  f"{', ' + profile['role_title'] if profile.get('role_title') else ''}.\n\nWhy: {profile['fit_note']}\n\n"
                  f"Approve or return it in Hiring: {workspace_link('hiring')}", "hiring", who, profile["company_id"])


@router.post("/analyst/hiring/profiles")
def feature_profile(body: ProfileIn, user: dict = Depends(need("talent.feature"))) -> dict[str, Any]:
    """Feature a candidate for a company. An Analyst's profile waits for an Admin's approval; an Admin's or the
    Super Admin's is shown to founders at once."""
    require_company(user, "talent.feature", body.company_id)
    ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            if body.interest_id is not None:
                cur.execute("SELECT company_id, status FROM candidate_interest WHERE id = %s FOR UPDATE", (body.interest_id,))
                row = cur.fetchone()
                if not row or row[0] != body.company_id:
                    raise HTTPException(status_code=404, detail="Candidate interest not found")
                if row[1] != "new":
                    raise HTTPException(status_code=409, detail="This candidate was already handled")
            pid, approval = _create_profile(cur, user, body, "interest" if body.interest_id else "fund")
            if body.interest_id is not None:
                cur.execute("UPDATE candidate_interest SET status = 'featured', profile_id = %s, handled_by = %s, handled_at = NOW() WHERE id = %s",
                            (pid, user["full_name"], body.interest_id))
            profile = _load_profile(cur, pid)
            ids = _tell_founders(cur, profile, user["full_name"]) if approval == "approved" else _ask_admins(cur, profile, user["full_name"])
        conn.commit()
    deliver_later(ids)
    return {"id": pid, "status": "featured", "approval": approval}


@router.patch("/analyst/hiring/profiles/{profile_id}")
def staff_profile_change(profile_id: int, body: ProfilePatch, user: dict = Depends(need("talent.feature", "talent.approve"))) -> dict[str, str]:
    """Withdraw a profile (the candidate is no longer available), feature it again, or correct it. A corrected
    profile from an Analyst goes back to an Admin for approval."""
    changes = body.model_dump(exclude_none=True, exclude={"status"})
    if "profile_url" in changes:
        changes["profile_url"] = _https(changes["profile_url"])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, full_name, status, approval FROM talent_profiles WHERE id = %s FOR UPDATE", (profile_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Profile not found")
            _require_hiring_company(user, row[0])
            if body.status == "featured" and row[2] != "withdrawn":
                raise HTTPException(status_code=409, detail="Only a withdrawn profile can be featured again")
            if body.status:
                cur.execute(
                    "UPDATE talent_profiles SET status = %s, featured_at = CASE WHEN %s = 'featured' THEN NOW() ELSE featured_at END, "
                    "founder_note = CASE WHEN %s = 'featured' THEN NULL ELSE founder_note END WHERE id = %s",
                    (body.status, body.status, body.status, profile_id),
                )
                _audit(cur, user, f"talent.{body.status}", row[1], None, row[0])
            if changes:
                if row[2] != "featured":
                    raise HTTPException(status_code=409, detail="A profile the founder already answered cannot be changed")
                for col, val in changes.items():  # columns come from the pydantic model
                    cur.execute(f"UPDATE talent_profiles SET {col} = %s WHERE id = %s", (val, profile_id))
                if not has_perm(user, "talent.approve"):
                    cur.execute("UPDATE talent_profiles SET approval = 'pending', review_note = NULL WHERE id = %s", (profile_id,))
                _audit(cur, user, "talent.edit", row[1], {"fields": sorted(changes)}, row[0])
            if not body.status and not changes:
                raise HTTPException(status_code=422, detail="Nothing to change")
        conn.commit()
    return {"status": body.status or row[2]}


@router.post("/analyst/hiring/profiles/{profile_id}/review")
def review_profile(profile_id: int, body: ReviewIn, user: dict = Depends(need("talent.approve"))) -> dict[str, str]:
    """An Admin (or the Super Admin) decides whether a profile is good enough for the founders."""
    note = _clean(body.note)
    if body.action == "return" and not note:
        raise HTTPException(status_code=422, detail="Say what should change when returning a profile")
    ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            profile = _load_profile(cur, profile_id)
            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")
            _require_hiring_company(user, profile["company_id"])
            if profile["approval"] != "pending":
                raise HTTPException(status_code=409, detail="This profile is not waiting for approval")
            approval = "approved" if body.action == "approve" else "returned"
            cur.execute("UPDATE talent_profiles SET approval = %s, review_note = %s, reviewed_by = %s, reviewed_at = NOW(), "
                        "featured_at = CASE WHEN %s = 'approved' THEN NOW() ELSE featured_at END WHERE id = %s",
                        (approval, note, user["full_name"], approval, profile_id))
            _audit(cur, user, f"talent.{body.action}", profile["full_name"], {"note": note}, profile["company_id"])
            if approval == "approved":
                ids = _tell_founders(cur, profile, user["full_name"])
            else:
                cur.execute("SELECT email, full_name, phone FROM users WHERE id = (SELECT featured_by FROM talent_profiles WHERE id = %s) AND active",
                            (profile_id,))
                ids = notify(cur, cur.fetchall(), f"Candidate returned: {profile['full_name']}"[:200],
                             f"{user['full_name']} returned {profile['full_name']} for {profile['company_name']}: {note}\n\n"
                             f"Correct it in Hiring: {workspace_link('hiring')}", "hiring", user["full_name"], profile["company_id"])
        conn.commit()
    deliver_later(ids)
    return {"approval": approval}


@router.post("/analyst/hiring/interest/{interest_id}/decline")
def decline_interest(interest_id: int, user: dict = Depends(need("talent.feature"))) -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, full_name, status FROM candidate_interest WHERE id = %s FOR UPDATE", (interest_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Candidate interest not found")
            require_company(user, "talent.feature", row[0])
            if row[2] != "new":
                raise HTTPException(status_code=409, detail="This candidate was already handled")
            cur.execute("UPDATE candidate_interest SET status = 'declined', handled_by = %s, handled_at = NOW() WHERE id = %s",
                        (user["full_name"], interest_id))
            _audit(cur, user, "interest.decline", row[1], None, row[0])
        conn.commit()
    return {"status": "declined"}


# ---------------------------------------------------------------- bulk upload of profiles
PROFILE_CSV_COLUMNS = ["company", "opening", "full_name", "headline", "experience_years", "location", "summary", "fit_note",
                       "profile_url", "consent"]


@router.get("/analyst/hiring/profiles/bulk-template")
def profiles_template(user: dict = Depends(need("talent.feature"))) -> Response:
    buf = io.StringIO()
    csv.writer(buf).writerows([
        PROFILE_CSV_COLUMNS,
        ["nimbus-mobility", "VP Engineering, battery systems (sample opening)", "Candidate Name (test)",
         "Director of Engineering, an EV company", "12", "Bengaluru",
         "Led a 30-person battery engineering team through two launches.",
         "Has scaled the kind of team the opening needs.", "https://www.linkedin.com/in/example", "yes"],
    ])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="candidate-profiles-template.csv"'})


@router.post("/analyst/hiring/profiles/bulk")
async def profiles_bulk(file: UploadFile = File(...), dry_run: bool = Form(True),
                        user: dict = Depends(need("talent.feature"))) -> dict[str, Any]:
    """Many candidate profiles from one CSV (company = short ID, opening = an open role's title or empty,
    consent = yes). dry_run=true checks every row and saves nothing. Analysts' rows wait for an Admin."""
    rows = read_csv_upload(await file.read(1_000_001), PROFILE_CSV_COLUMNS, ("opening", "experience_years", "location", "profile_url"))
    allowed = company_scope(user, "talent.feature")
    checked, valid = [], []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for n, r in enumerate(rows, start=2):
                errors: list[str] = []
                cur.execute("SELECT id, name FROM companies WHERE slug = %s AND status = 'active'", ((r.get("company") or "").strip().lower(),))
                co = cur.fetchone()
                role_id = None
                if not co:
                    errors.append(f"company: no active company with short ID {r.get('company')!r}")
                elif allowed is not None and co[0] not in allowed:
                    errors.append(f"company: you are not assigned to {co[1]}")
                elif r.get("opening"):
                    cur.execute("SELECT id FROM hiring_roles WHERE company_id = %s AND status = 'open' AND lower(title) = lower(%s)",
                                (co[0], r["opening"].strip()))
                    found = cur.fetchone()
                    if not found:
                        errors.append(f"opening: {co[1]} has no open role called {r['opening']!r}")
                    else:
                        role_id = found[0]
                if (r.get("consent") or "").strip().lower() not in ("yes", "y", "true", "1"):
                    errors.append("consent must be yes (the candidate agreed to be shared with this company)")
                body = None
                try:
                    years = (r.get("experience_years") or "").strip()
                    body = ProfileIn(company_id=co[0] if co else 0, role_id=role_id, full_name=r.get("full_name", ""),
                                     headline=r.get("headline", ""), experience_years=int(years) if years else None,
                                     location=r.get("location") or None, summary=r.get("summary", ""), fit_note=r.get("fit_note", ""),
                                     profile_url=r.get("profile_url") or None, consent_confirmed=True)
                    if body.profile_url and not body.profile_url.lower().startswith("https://"):
                        errors.append("profile_url must start with https://")
                except (ValidationError, ValueError) as e:
                    msgs = e.errors() if isinstance(e, ValidationError) else [{"loc": ["experience_years"], "msg": "must be a whole number"}]
                    errors += [f"{'.'.join(str(x) for x in m['loc'])}: {m['msg']}" for m in msgs]
                checked.append({"row": n, "full_name": r.get("full_name", ""), "company": co[1] if co else r.get("company"), "errors": errors})
                if not errors and body:
                    valid.append(body)
            ok = len(valid) == len(rows)
            if dry_run or not ok:
                return {"saved": 0, "ok": ok, "rows": checked}
            ids: list[int] = []
            for body in valid:
                pid, approval = _create_profile(cur, user, body, "bulk")
                if approval == "approved":
                    ids += _tell_founders(cur, _load_profile(cur, pid), user["full_name"])
            if not has_perm(user, "talent.approve") and valid:
                cur.execute("""SELECT DISTINCT u.email, u.full_name, u.phone FROM users u JOIN user_roles r ON r.user_id = u.id
                               WHERE u.active AND u.account_type = 'staff' AND r.role_code IN ('admin', 'super_admin')""")
                ids += notify(cur, cur.fetchall(), f"{len(valid)} candidate profiles to approve",
                              f"{user['full_name']} uploaded {len(valid)} candidate profiles. Approve or return them in Hiring: "
                              f"{workspace_link('hiring')}", "hiring", user["full_name"], None)
            _audit(cur, user, "talent.bulk", f"{len(valid)} profiles")
        conn.commit()
    deliver_later(ids)
    return {"saved": len(valid), "ok": True, "rows": checked}


# ---------------------------------------------------------------- public interest link
MAX_PER_HOUR = 6


def _rate_limited(request: Request) -> bool:
    """At most MAX_PER_HOUR interest submissions per address per hour. Counted in the database, so the limit
    holds across several API processes. The address is the connecting client; behind Caddy, uvicorn's
    --proxy-headers already sets it from the proxy (a visitor-supplied X-Forwarded-For is not trusted here)."""
    key = request.client.host if request.client else "unknown"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('public_form:' || %s))", (key,))
            cur.execute("DELETE FROM public_form_hits WHERE client = %s AND created_at < NOW() - INTERVAL '1 day'", (key,))
            cur.execute("SELECT COUNT(*) FROM public_form_hits WHERE client = %s AND created_at > NOW() - INTERVAL '1 hour'",
                        (key,))
            if cur.fetchone()[0] >= MAX_PER_HOUR:
                return True
            cur.execute("INSERT INTO public_form_hits (client) VALUES (%s)", (key,))
        conn.commit()
    return False


def _public_role(cur, token: str) -> tuple:
    cur.execute(
        """
        SELECT r.id, r.company_id, c.name, r.title, r.seniority, r.location, r.notes, c.city, c.website
        FROM hiring_roles r JOIN companies c ON c.id = r.company_id
        WHERE r.public_token = %s AND r.status = 'open' AND c.status = 'active'
        """,
        (token,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="This opening is no longer taking interest. Thank you for looking.")
    return row


@router.get("/public/opening/{token}")
def public_opening(token: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            r = _public_role(cur, token)
    return {"company": r[2], "title": r[3], "seniority": r[4], "location": r[5], "notes": r[6], "city": r[7], "website": r[8]}


@router.post("/public/opening/{token}/interest")
def public_interest(token: str, body: InterestIn, request: Request) -> dict[str, str]:
    if body.website:  # the hidden field was filled: treat as a bot, answer as if it worked
        return {"status": "Your details are with the Demo Ventures team. They will be in touch if there is a fit."}
    if not body.consent:
        raise HTTPException(status_code=422, detail="Please agree that Demo Ventures may share your details with this company")
    if _rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many submissions from this connection. Please try again in an hour.")
    url = _https(body.profile_url)
    ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            role_id, company_id, company, title = _public_role(cur, token)[:4]
            cur.execute(
                """
                INSERT INTO candidate_interest (role_id, company_id, full_name, email, phone, headline, experience_years,
                    location, profile_url, note, consent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (role_id, email) DO NOTHING RETURNING id
                """,
                (role_id, company_id, body.full_name.strip(), body.email.lower(), _clean(body.phone), body.headline.strip(),
                 body.experience_years, _clean(body.location), url, _clean(body.note)),
            )
            new = cur.fetchone()
            if new:
                ids = notify(cur, company_team(cur, company_id), f"New candidate interest: {body.full_name.strip()} for {title}"[:200],
                             f"{body.full_name.strip()} ({body.headline.strip()}) registered interest in {title} at {company} "
                             f"through the interest link.\n\nScreen them and feature them for the founders in Hiring: {workspace_link('hiring')}",
                             "interest", "interest link", company_id)
        conn.commit()
    deliver_later(ids)
    return {"status": "Your details are with the Demo Ventures team. They will be in touch if there is a fit."}
