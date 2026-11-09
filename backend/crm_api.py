"""Portfolio CRM pieces added for IC sign-off (23 Oct): request conversations, the staff list used for
owners, company notes and interactions, and clearing a sign-in lock.

    GET/POST /api/founder/help/{ref}/messages            founder conversation on one request
    GET/POST /api/analyst/work-items/{id}/messages       the same conversation, from the Demo Ventures side
    GET      /api/analyst/staff-names                    active Demo Ventures people (for owner pickers)
    GET/POST /api/admin/companies/{id}/notes             internal notes, calls and meetings per company
    POST     /api/admin/users/{id}/unlock                clear failed sign-ins for an account
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.admin_api import _audit, _can_manage_staff
from backend.db import get_conn
from backend.messaging import deliver_later, notify, portal_link
from backend.security import (
    auth_session,
    company_scope,
    founder_company,
    iso,
    need,
    require_company,
    require_founder,
    require_founder_or_preview,
    require_perm,
)

router = APIRouter(prefix="/api")

NOTE_KINDS = ("note", "call", "meeting", "email")
NOTE_LABELS = {"note": "Note", "call": "Call", "meeting": "Meeting", "email": "Email"}


class MessageIn(BaseModel):
    body: str = Field(min_length=2, max_length=4000)


class NoteIn(BaseModel):
    kind: str = "note"
    body: str = Field(min_length=3, max_length=2000)


def _messages(cur, help_id: int) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT author_name, from_fund, body, created_at FROM help_messages WHERE help_id = %s ORDER BY created_at, id",
        (help_id,),
    )
    return [{"author": r[0], "from_fund": r[1], "body": r[2], "at": iso(r[3])} for r in cur.fetchall()]


def _founder_request(cur, ref: str, company_id: int) -> tuple:
    cur.execute(
        """
        SELECT h.id, h.subject, h.context, h.created_at, u.full_name, w.id, w.internal_status
        FROM founder_help h JOIN users u ON u.id = h.user_id LEFT JOIN work_items w ON w.help_id = h.id
        WHERE h.public_ref = %s AND h.company_id = %s
        """,
        (ref, company_id),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    return row


# ---------------------------------------------------------------- request conversations (founder side)
@router.get("/founder/help/{ref}/messages")
def founder_messages(ref: str, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder_or_preview(user)
    cid = founder_company(user)[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            help_id, subject, context, created, author, _, _ = _founder_request(cur, ref, cid)
            first = {"author": author, "from_fund": False, "body": context or subject, "at": iso(created)}
            return {"ref": ref, "messages": [first, *_messages(cur, help_id)]}


@router.post("/founder/help/{ref}/messages")
def founder_follow_up(ref: str, body: MessageIn, user: dict = Depends(auth_session)) -> dict[str, Any]:
    """A follow-up continues the same request. A resolved request is reopened for the Demo Ventures team."""
    require_founder(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            help_id, _, _, _, _, work_id, status = _founder_request(cur, ref, user["company_id"])
            cur.execute(
                "INSERT INTO help_messages (help_id, author_id, author_name, from_fund, body) VALUES (%s, %s, %s, FALSE, %s)",
                (help_id, user["id"], user["full_name"], body.body.strip()),
            )
            reopened = status == "resolved"
            if reopened:
                cur.execute("UPDATE work_items SET internal_status = 'queued', updated_at = NOW() WHERE id = %s", (work_id,))
                cur.execute("UPDATE founder_help SET founder_status = 'Demo Ventures is reviewing your follow-up' WHERE id = %s", (help_id,))
            cur.execute("UPDATE founder_help SET updated_at = NOW() WHERE id = %s", (help_id,))
        conn.commit()
    return {"status": "sent", "reopened": reopened}


# ---------------------------------------------------------------- request conversations (Demo Ventures side)
def _work_item(cur, user: dict[str, Any], work_id: int) -> tuple:
    cur.execute(
        """
        SELECT h.id, h.public_ref, h.company_id, h.subject, h.context, h.created_at, u.full_name
        FROM work_items w JOIN founder_help h ON h.id = w.help_id JOIN users u ON u.id = h.user_id WHERE w.id = %s
        """,
        (work_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    allowed = company_scope(user, "requests.handle")
    if allowed is not None and row[2] not in allowed:
        raise HTTPException(status_code=403, detail="You are not assigned to this company")
    return row


@router.get("/analyst/work-items/{work_id}/messages")
def staff_messages(work_id: int, user: dict = Depends(need("requests.handle"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            help_id, ref, _, subject, context, created, author = _work_item(cur, user, work_id)
            first = {"author": author, "from_fund": False, "body": context or subject, "at": iso(created)}
            return {"ref": ref, "messages": [first, *_messages(cur, help_id)]}


@router.post("/analyst/work-items/{work_id}/messages")
def staff_reply(work_id: int, body: MessageIn, user: dict = Depends(need("requests.handle"))) -> dict[str, str]:
    """A reply the founder sees in the same conversation."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            help_id, ref, cid, subject, _, _, _ = _work_item(cur, user, work_id)
            cur.execute(
                "INSERT INTO help_messages (help_id, author_id, author_name, from_fund, body) VALUES (%s, %s, %s, TRUE, %s)",
                (help_id, user["id"], user["full_name"], body.body.strip()),
            )
            cur.execute("UPDATE founder_help SET updated_at = NOW() WHERE id = %s", (help_id,))
            _audit(cur, user, "request.reply", ref, None, cid)
            cur.execute("SELECT u.email, u.full_name, u.phone FROM founder_help h JOIN users u ON u.id = h.user_id "
                        "WHERE h.id = %s AND u.active", (help_id,))
            founder = cur.fetchall()
            ids = notify(cur, founder, f"Reply from Demo Ventures on {ref}: {subject}"[:200],
                         f"{user['full_name']} replied to your request \"{subject}\":\n\n{body.body.strip()}\n\n"
                         f"Reply or follow up in the portal: {portal_link('requests')}", "reply", user["full_name"], cid)
        conn.commit()
    deliver_later(ids)
    return {"status": "sent"}


# ---------------------------------------------------------------- people who can own a request or a playbook
@router.get("/analyst/staff-names")
def staff_names(user: dict = Depends(need("requests.handle", "playbooks.manage"))) -> list[dict[str, str]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.full_name, COALESCE((SELECT r.role_code FROM user_roles r WHERE r.user_id = u.id LIMIT 1), '')
                FROM users u WHERE u.account_type = 'staff' AND u.active ORDER BY u.full_name
                """
            )
            return [{"name": r[0], "tier": r[1]} for r in cur.fetchall()]


def check_staff_name(cur, name: str | None) -> str | None:
    """An owner shown to founders must be an active Demo Ventures account (or empty)."""
    name = (name or "").strip()
    if not name:
        return None
    cur.execute("SELECT full_name FROM users WHERE account_type = 'staff' AND active AND lower(full_name) = lower(%s)", (name,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=422, detail=f"{name} has no active Demo Ventures account. Choose someone from the list")
    return row[0]


# ---------------------------------------------------------------- company notes and interactions (internal)
@router.get("/admin/companies/{company_id}/notes")
def list_notes(company_id: int, user: dict = Depends(need("companies.view"))) -> list[dict[str, Any]]:
    require_company(user, "companies.view", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, body, author_name, created_at FROM company_notes WHERE company_id = %s ORDER BY created_at DESC LIMIT 50",
                (company_id,),
            )
            return [{"id": r[0], "kind": r[1], "kind_label": NOTE_LABELS.get(r[1], r[1]), "body": r[2], "author": r[3], "at": iso(r[4])}
                    for r in cur.fetchall()]


@router.post("/admin/companies/{company_id}/notes")
def add_note(company_id: int, body: NoteIn, user: dict = Depends(need("companies.view"))) -> dict[str, Any]:
    """Demo Ventures-only notes: calls, meetings and emails with the company. Founders never see them."""
    require_company(user, "companies.view", company_id)
    if body.kind not in NOTE_KINDS:
        raise HTTPException(status_code=422, detail=f"Type must be one of {', '.join(NOTE_KINDS)}")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Company not found")
            cur.execute(
                "INSERT INTO company_notes (company_id, kind, body, author_id, author_name) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (company_id, body.kind, body.body.strip(), user["id"], user["full_name"]),
            )
            nid = cur.fetchone()[0]
            _audit(cur, user, "company.note", row[0], {"kind": body.kind}, company_id)
        conn.commit()
    return {"id": nid}


# ---------------------------------------------------------------- clear a sign-in lock
@router.post("/admin/users/{user_id}/unlock")
def unlock_user(user_id: int, user: dict = Depends(need("founders.manage", "staff.manage", "admins.manage"))) -> dict[str, str]:
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
                require_perm(user, "staff.manage", "admins.manage")
                _can_manage_staff(cur, user, user_id)
            cur.execute("DELETE FROM login_failures WHERE email = %s", (email,))
            _audit(cur, user, "user.unlock", email, None, company_id)
        conn.commit()
    return {"status": "unlocked"}
