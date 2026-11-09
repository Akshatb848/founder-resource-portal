"""Outbox, sending content to founders, and sign-in links (meeting of 23 Oct 2026).

    GET  /api/admin/email-status                  is email delivery set up (or test mode)
    GET  /api/admin/outbox                        messages sent or prepared, with WhatsApp / email-app links
    POST /api/admin/outbox/{id}/send              deliver (again) one message
    POST /api/admin/messages/invite-preview       the invite a founder will get, before it is sent
    GET  /api/admin/messages/sendable             published resources, events and updates that can be sent
    POST /api/admin/messages/preview              recipients and wording for a send, before sending
    POST /api/admin/messages/send                 email the chosen founders (+ WhatsApp links per person)
    GET  /api/admin/messages/history              earlier sends
    GET  /api/auth/link/{token}                   (public) who an invite/reset link is for
    POST /api/auth/set-password                   (public) set a password with a link; signs the person in
    POST /api/auth/forgot                         (public) email a reset link
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.admin_api import _audit
from backend.audience import Audience, clean_audience, company_names, describe
from backend.auth_store import create_session, load_access
from backend.db import get_conn
from backend.messaging import (
    SIGN_OFF,
    deliver,
    deliver_later,
    email_configured,
    find_token,
    invite_message,
    link,
    mailto_url,
    make_token,
    portal_link,
    queue_email,
    reset_message,
    whatsapp_url,
)
from backend.config import PORTAL_URL, SMTP_FROM
from backend.security import company_scope, iso, need

router = APIRouter(prefix="/api")
IST_FMT = "%a %d %b %Y, %I:%M %p IST"


# ---------------------------------------------------------------- status and outbox
@router.get("/admin/email-status")
def email_status(user: dict = Depends(need("overview.view"))) -> dict[str, Any]:
    return {"configured": email_configured(), "from": SMTP_FROM if email_configured() else None, "portal_url": PORTAL_URL,
            "mode": "live" if email_configured() else "test"}


def _outbox_row(r: tuple) -> dict[str, Any]:
    if r[5] == "otp":  # staff never see a person's sign-in code; the email itself still carries it
        r = (*r[:3], re.sub(r"\b\d{6}\b", "••••••", r[3] or ""), re.sub(r"\b\d{6}\b", "••••••", r[4] or ""), *r[5:12], None)
    return {"id": r[0], "to_email": r[1], "to_name": r[2], "subject": r[3], "body": r[4], "kind": r[5], "company": r[6],
            "status": r[7], "error": r[8], "created_by": r[9], "created_at": iso(r[10]), "sent_at": iso(r[11]),
            "whatsapp_url": whatsapp_url(r[12], f"{r[3]}\n\n{r[4]}"), "mailto_url": mailto_url(r[1], r[3], r[4]),
            "has_phone": bool(r[12])}


@router.get("/admin/outbox")
def outbox(limit: int = 100, user: dict = Depends(need("overview.view"))) -> list[dict[str, Any]]:
    """Messages for the companies this person serves, plus anything they prepared themselves."""
    allowed = company_scope(user, "companies.view")
    ids = list(allowed) if allowed is not None else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.id, o.to_email, o.to_name, o.subject, o.body, o.kind, c.name, o.status, o.error, o.created_by,
                    o.created_at, o.sent_at, o.to_phone
                FROM email_outbox o LEFT JOIN companies c ON c.id = o.company_id
                WHERE %s::int[] IS NULL OR o.company_id = ANY(%s::int[]) OR o.created_by = %s
                ORDER BY o.created_at DESC, o.id DESC LIMIT %s
                """,
                (ids, ids, user["full_name"], max(1, min(limit, 500))),
            )
            return [_outbox_row(r) for r in cur.fetchall()]


@router.post("/admin/outbox/{message_id}/send")
def send_again(message_id: int, user: dict = Depends(need("overview.view"))) -> dict[str, Any]:
    allowed = company_scope(user, "companies.view")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id, created_by, status FROM email_outbox WHERE id = %s", (message_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Message not found")
            if allowed is not None and row[0] not in allowed and row[1] != user["full_name"]:
                raise HTTPException(status_code=403, detail="This message is for another company")
            if row[2] == "sent":
                raise HTTPException(status_code=409, detail="This message was already sent")
    deliver([message_id])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, error FROM email_outbox WHERE id = %s", (message_id,))
            status, error = cur.fetchone()
    return {"status": status, "error": error}


# ---------------------------------------------------------------- invite preview
class InvitePreviewIn(BaseModel):
    company_id: int
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    note: str | None = Field(default=None, max_length=600)


@router.post("/admin/messages/invite-preview")
def invite_preview(body: InvitePreviewIn, user: dict = Depends(need("founders.manage"))) -> dict[str, str]:
    """Exactly what the founder will receive; the real link is created when the invite is sent."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM companies WHERE id = %s", (body.company_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Company not found")
    placeholder = "[Personal sign-in link, created when you send the invite]"
    subject, text, wa = invite_message(body.full_name, row[0], user["full_name"], placeholder, body.note)
    return {"subject": subject, "body": text, "whatsapp_text": wa, "email_mode": "live" if email_configured() else "test"}


# ---------------------------------------------------------------- send content to founders
class SendIn(Audience):
    kind: Literal["resource", "event", "update", "custom"]
    item_id: int | None = None
    subject: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=4000)


def _recipients(cur, aud: dict[str, Any]) -> list[dict[str, Any]]:
    """Active founders of active companies the audience reaches."""
    cur.execute(
        f"""
        SELECT u.id, u.full_name, u.email, u.phone, c.id, c.name
        FROM users u JOIN companies c ON c.id = u.company_id
        WHERE u.account_type = 'founder' AND u.active AND c.status = 'active'
          AND fp_visible(%s, %s, %s, %s, c.id)
        ORDER BY c.name, u.full_name
        """,
        (aud["company_id"], aud["target_company_ids"], aud["target_sectors"], aud["target_stages"]),
    )
    return [{"user_id": r[0], "name": r[1], "email": r[2], "phone": r[3], "company_id": r[4], "company": r[5]}
            for r in cur.fetchall()]


def _item_text(cur, kind: str, item_id: int | None) -> tuple[str, str]:
    """Default subject and body for a published item."""
    if kind == "custom":
        return "", ""
    if item_id is None:
        raise HTTPException(status_code=422, detail="Choose what to send")
    if kind == "resource":
        cur.execute("SELECT title, description, category FROM resources WHERE id = %s AND status = 'approved'", (item_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=422, detail="Only an approved resource can be sent")
        return (f"New in your Resource Library: {r[0]}",
                f"{r[0]} ({r[2]})\n{r[1]}\n\nOpen it in the portal: {portal_link('resources')}")
    if kind == "event":
        cur.execute("SELECT title, description, location, starts_at FROM events WHERE id = %s AND active AND approval = 'approved'",
                    (item_id,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=422, detail="Only an approved, active event can be sent")
        from datetime import timedelta, timezone
        when = r[3].astimezone(timezone(timedelta(hours=5, minutes=30))).strftime(IST_FMT)
        return (f"You're invited: {r[0]}",
                f"{r[0]}\nWhen: {when}\nWhere: {r[2]}\n{(r[1] or '').strip()}\n\nRSVP in the portal: {portal_link('events')}")
    cur.execute("SELECT title, summary, source FROM sector_updates WHERE id = %s AND approval = 'approved' AND (expires_at IS NULL OR expires_at > NOW())",
                (item_id,))
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=422, detail="Only an approved, live sector update can be sent")
    return (f"Sector update: {r[0]}", f"{r[0]}\n{r[1]}\nSource: {r[2]}\n\nRead it in the portal: {portal_link('updates')}")


def _personal(name: str, body: str) -> str:
    first = (name or "").split(" ")[0] or "there"
    return f"Hi {first},\n\n{body.strip()}\n\n{SIGN_OFF}"


def _item_audience(cur, kind: str, item_id: int | None) -> dict[str, Any] | None:
    """An item's own audience, so a send never reaches founders who cannot open the item."""
    table = {"resource": "resources", "event": "events", "update": "sector_updates"}.get(kind)
    if not table or item_id is None:
        return None
    cur.execute(f"SELECT company_id, target_company_ids, target_sectors, target_stages FROM {table} WHERE id = %s", (item_id,))
    return cur.fetchone()


def _prepare(cur, user: dict[str, Any], body: SendIn) -> tuple[list[dict[str, Any]], str, str]:
    aud = clean_audience(cur, body, company_scope(user, "companies.view"))
    default_subject, default_body = _item_text(cur, body.kind, body.item_id)
    subject = (body.subject or "").strip() or default_subject
    message = (body.message or "").strip() or default_body
    if not subject or len(message) < 10:
        raise HTTPException(status_code=422, detail="Write a subject and a message of at least 10 characters")
    people = _recipients(cur, aud)
    own = _item_audience(cur, body.kind, body.item_id)
    if own:
        cur.execute("SELECT id FROM companies WHERE fp_visible(%s, %s, %s, %s, id)", own)
        allowed_ids = {r[0] for r in cur.fetchall()}
        people = [p for p in people if p["company_id"] in allowed_ids]
    return people, subject, message


@router.get("/admin/messages/sendable")
def sendable(user: dict = Depends(need("content.submit", "news.publish", "events.manage"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, category FROM resources WHERE status = 'approved' ORDER BY reviewed_at DESC NULLS LAST, id DESC LIMIT 200")
            res = [{"id": r[0], "title": f"{r[1]} ({r[2]})"} for r in cur.fetchall()]
            cur.execute("SELECT id, title, starts_at FROM events WHERE active AND approval = 'approved' AND starts_at > NOW() ORDER BY starts_at LIMIT 100")
            evs = [{"id": r[0], "title": r[1], "starts_at": iso(r[2])} for r in cur.fetchall()]
            cur.execute("SELECT id, title FROM sector_updates WHERE approval = 'approved' AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY published_at DESC LIMIT 100")
            ups = [{"id": r[0], "title": r[1]} for r in cur.fetchall()]
    return {"resource": res, "event": evs, "update": ups, "email_mode": "live" if email_configured() else "test"}


@router.post("/admin/messages/preview")
def preview_send(body: SendIn, user: dict = Depends(need("content.submit", "news.publish", "events.manage"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            people, subject, message = _prepare(cur, user, body)
    sample = people[0]["name"] if people else "Founder"
    return {"recipients": [{k: v for k, v in p.items() if k != "user_id"} for p in people], "subject": subject,
            "message": message, "example": _personal(sample, message), "email_mode": "live" if email_configured() else "test"}


@router.post("/admin/messages/send")
def send(body: SendIn, user: dict = Depends(need("content.submit", "news.publish", "events.manage"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            people, subject, message = _prepare(cur, user, body)
            if not people:
                raise HTTPException(status_code=422, detail="No active founder matches this audience")
            ids, out = [], []
            for p in people:
                text = _personal(p["name"], message)
                mid = queue_email(cur, p["email"], p["name"], subject, text, "distribution", user["full_name"], p["company_id"], p["phone"])
                ids.append(mid)
                out.append({"name": p["name"], "company": p["company"], "email": p["email"], "outbox_id": mid,
                            "whatsapp_url": whatsapp_url(p["phone"], f"{subject}\n\n{text}"), "has_phone": bool(p["phone"])})
            cur.execute(
                """
                INSERT INTO distributions (kind, item_id, subject, audience, recipients, sent_by)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (body.kind, body.item_id, subject, json.dumps(clean_audience(cur, body, company_scope(user, "companies.view"))),
                 len(people), user["full_name"]),
            )
            _audit(cur, user, "message.send", subject, {"kind": body.kind, "recipients": len(people)})
        conn.commit()
    deliver_later(ids)
    return {"sent_to": len(out), "recipients": out, "email_mode": "live" if email_configured() else "test"}


@router.get("/admin/messages/history")
def history(user: dict = Depends(need("content.submit", "news.publish", "events.manage"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, kind, subject, audience, recipients, sent_by, created_at FROM distributions ORDER BY created_at DESC LIMIT 50")
            rows = cur.fetchall()
            names = company_names(cur)
    out = []
    for r in rows:
        a = json.loads(r[3] or "{}")
        who = describe(names.get(a.get("company_id")), a.get("target_company_ids"), a.get("target_sectors"), a.get("target_stages"), names)
        out.append({"id": r[0], "kind": r[1], "subject": r[2], "audience": who, "recipients": r[4], "sent_by": r[5], "at": iso(r[6])})
    return out


# ---------------------------------------------------------------- sign-in links (public)
class SetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class ForgotIn(BaseModel):
    email: EmailStr


@router.get("/auth/link/{token}")
def link_info(token: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            row = find_token(cur, token)
    if not row:
        raise HTTPException(status_code=404, detail="This link has expired or was already used. Ask your Demo Ventures team for a new one.")
    return {"purpose": row[2], "email": row[3], "full_name": row[4], "company": row[5]}


@router.post("/auth/set-password")
def set_password(body: SetPasswordIn) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            row = find_token(cur, body.token)
            if not row:
                raise HTTPException(status_code=404, detail="This link has expired or was already used. Ask your Demo Ventures team for a new one.")
            tid, uid, purpose, email = row[0], row[1], row[2], row[3]
            pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
            cur.execute("UPDATE users SET password_hash = %s, last_login_at = NOW() WHERE id = %s", (pw_hash, uid))
            cur.execute("UPDATE account_tokens SET used_at = NOW() WHERE id = %s", (tid,))
            cur.execute("DELETE FROM user_sessions WHERE user_id = %s", (uid,))  # a reset ends other sessions
            cur.execute("DELETE FROM login_failures WHERE email = %s", (email,))
            cur.execute("INSERT INTO sign_ins (user_id) VALUES (%s)", (uid,))
            cur.execute(
                """
                SELECT u.id, u.email, u.full_name, u.account_type, u.company_id, c.name, c.sector
                FROM users u LEFT JOIN companies c ON c.id = u.company_id WHERE u.id = %s
                """,
                (uid,),
            )
            u = cur.fetchone()
            user = load_access(cur, {"id": u[0], "email": u[1], "full_name": u[2], "account_type": u[3],
                                     "company_id": u[4], "company_name": u[5], "sector": u[6]})
            cur.execute(
                "INSERT INTO admin_audit (actor, action, target, details, company_id) VALUES (%s, %s, %s, '{}', %s)",
                (email, "account.password_set" if purpose == "invite" else "account.password_reset", email, u[4]),
            )
        conn.commit()
    token = create_session(uid)
    return {"token": token, "user": user, "redirect": "/" if user["account_type"] == "founder" else "/analyst.html"}


@router.post("/auth/forgot")
def forgot(body: ForgotIn, request: Request) -> dict[str, str]:
    """Always answers the same way, so it never reveals whether an email has an account."""
    email = body.email.lower()
    ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM account_tokens t JOIN users u ON u.id = t.user_id "
                        "WHERE u.email = %s AND t.purpose = 'reset' AND t.created_at > NOW() - INTERVAL '15 minutes'", (email,))
            recent = cur.fetchone()[0]
            cur.execute("SELECT id, full_name, company_id, phone FROM users WHERE email = %s AND active", (email,))
            row = cur.fetchone()
            if row and recent < 3:
                token = make_token(cur, row[0], "reset", "self-service")
                subject, text, _ = reset_message(row[1], "", link("reset", token))
                ids.append(queue_email(cur, email, row[1], subject, text, "reset", "self-service", row[2], row[3]))
        conn.commit()
    deliver_later(ids)
    return {"status": "If this email has an account, a reset link is on its way. No email? Ask your Demo Ventures team."}
