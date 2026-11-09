"""Messages: one-to-one chat between founders and the Demo Ventures team (partner review, 4 Nov 2026).

    GET  /api/chat/contacts            the people this user can message, with the last message and unread count
    GET  /api/chat/thread/{other_id}   the conversation with one person (marks their messages as read)
    POST /api/chat/thread/{other_id}   send a message, with an optional file (multipart: body, file)
    GET  /api/chat/file/{message_id}   download an attachment (participants only)
    GET  /api/chat/unread              unread count, for the sidebar badge

Who can talk to whom: a founder messages their company's relationship manager and portfolio analyst, the
Super Admin, and anyone at Demo Ventures who has already written to them. Staff message the founders of the
companies they may view (company_scope "companies.view"). Founders never message each other here: the
Demo Ventures network (advisors, partners, peers) is reached through Connect.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.config import MAX_UPLOAD_MB, UPLOAD_DIR
from backend.db import get_conn
from backend.security import auth_session, company_scope, iso

router = APIRouter(prefix="/api/chat")

CHAT_DIR = UPLOAD_DIR / "chat"
ALLOWED = {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".png", ".jpg", ".jpeg", ".txt"}
MAX_BODY = 4000


def _is_staff(user: dict[str, Any]) -> bool:
    return user.get("account_type") == "staff"


def _founder_contacts(cur, user: dict[str, Any]) -> set[int]:
    """Staff a founder may message: their company's Demo Ventures team, the Super Admin, and anyone who wrote first."""
    cur.execute(
        """
        SELECT DISTINCT ON (role) user_id FROM company_assignments WHERE company_id = %s AND user_id IS NOT NULL
        ORDER BY role, effective_from DESC, id DESC
        """, (user["company_id"],))
    ids = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT u.id FROM users u JOIN user_roles r ON r.user_id = u.id WHERE r.role_code = 'super_admin' AND u.active")
    ids |= {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT staff_id FROM chat_messages WHERE founder_id = %s", (user["id"],))
    ids |= {r[0] for r in cur.fetchall()}
    return ids


def _staff_contacts(cur, user: dict[str, Any]) -> set[int]:
    """Founders a staff member may message: the active founders of the companies they may view."""
    allowed = company_scope(user, "companies.view")
    cur.execute("SELECT id, company_id FROM users WHERE account_type = 'founder' AND active")
    return {uid for uid, cid in cur.fetchall() if allowed is None or cid in allowed}


def _pair(cur, user: dict[str, Any], other_id: int) -> tuple[int, int]:
    """(founder_id, staff_id) of a conversation this user may take part in; 403 otherwise."""
    if _is_staff(user):
        if other_id not in _staff_contacts(cur, user):
            raise HTTPException(status_code=403, detail="You can message the founders of your own companies")
        return other_id, user["id"]
    if user.get("account_type") != "founder" or not user.get("company_id"):
        raise HTTPException(status_code=403, detail="Messages are for founders and the Demo Ventures team")
    if other_id not in _founder_contacts(cur, user):
        raise HTTPException(status_code=403, detail="You can message your Demo Ventures team")
    return user["id"], other_id


@router.get("/contacts")
def contacts(user: dict = Depends(auth_session)) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            ids = _staff_contacts(cur, user) if _is_staff(user) else (_founder_contacts(cur, user) if user.get("company_id") else set())
            if not ids:
                return []
            me_col, other_col = ("staff_id", "founder_id") if _is_staff(user) else ("founder_id", "staff_id")
            cur.execute(
                f"""
                SELECT u.id, u.full_name, u.title, c.name,
                    (SELECT m.body FROM chat_messages m WHERE m.{me_col} = %s AND m.{other_col} = u.id ORDER BY m.id DESC LIMIT 1),
                    (SELECT m.file_name FROM chat_messages m WHERE m.{me_col} = %s AND m.{other_col} = u.id ORDER BY m.id DESC LIMIT 1),
                    (SELECT MAX(m.created_at) FROM chat_messages m WHERE m.{me_col} = %s AND m.{other_col} = u.id),
                    (SELECT COUNT(*) FROM chat_messages m WHERE m.{me_col} = %s AND m.{other_col} = u.id AND m.sender_id = u.id AND m.read_at IS NULL),
                    COALESCE((SELECT string_agg(DISTINCT CASE a.role WHEN 'relationship_partner' THEN 'Relationship manager'
                        WHEN 'portfolio_analyst' THEN 'Portfolio analyst' END, ', ')
                        FROM (SELECT DISTINCT ON (role) role, user_id FROM company_assignments WHERE company_id = %s
                              ORDER BY role, effective_from DESC, id DESC) a WHERE a.user_id = u.id), '')
                FROM users u LEFT JOIN companies c ON c.id = u.company_id
                WHERE u.id = ANY(%s) AND u.active
                """, (user["id"], user["id"], user["id"], user["id"], user.get("company_id"), list(ids)))
            rows = cur.fetchall()
    out = [{"id": r[0], "name": r[1], "title": r[2] or "", "company": r[3] or ("Demo Ventures" if not _is_staff(user) else ""),
            "last_message": (r[4] or (f"Sent a file: {r[5]}" if r[5] else "")), "last_at": iso(r[6]), "unread": r[7],
            "role": r[8] or ("Demo Ventures team" if not _is_staff(user) else "Founder")} for r in rows]
    # Conversations with recent messages first, then everyone else by name.
    with_msgs = sorted([x for x in out if x["last_at"]], key=lambda x: x["last_at"], reverse=True)
    return with_msgs + sorted([x for x in out if not x["last_at"]], key=lambda x: x["name"].lower())


@router.get("/unread")
def unread(user: dict = Depends(auth_session)) -> dict[str, int]:
    col = "staff_id" if _is_staff(user) else "founder_id"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM chat_messages WHERE {col} = %s AND sender_id <> %s AND read_at IS NULL", (user["id"], user["id"]))
            return {"unread": cur.fetchone()[0]}


@router.get("/thread/{other_id}")
def thread(other_id: int, user: dict = Depends(auth_session)) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            founder_id, staff_id = _pair(cur, user, other_id)
            cur.execute("SELECT full_name, title FROM users WHERE id = %s", (other_id,))
            name, title = cur.fetchone() or ("", "")
            cur.execute("UPDATE chat_messages SET read_at = NOW() WHERE founder_id = %s AND staff_id = %s AND sender_id = %s AND read_at IS NULL",
                        (founder_id, staff_id, other_id))
            cur.execute(
                """
                SELECT m.id, m.sender_id, u.full_name, m.body, m.file_name, m.file_size, m.created_at, m.read_at
                FROM chat_messages m JOIN users u ON u.id = m.sender_id
                WHERE m.founder_id = %s AND m.staff_id = %s ORDER BY m.id
                """, (founder_id, staff_id))
            msgs = [{"id": r[0], "mine": r[1] == user["id"], "author": r[2], "body": r[3] or "", "file_name": r[4], "file_size": r[5],
                     "at": iso(r[6]), "read": r[7] is not None} for r in cur.fetchall()]
        conn.commit()
    return {"with": {"id": other_id, "name": name, "title": title or ""}, "messages": msgs}


@router.post("/thread/{other_id}")
async def send(other_id: int, body: str = Form(""), file: UploadFile | None = File(None),
               user: dict = Depends(auth_session)) -> dict[str, Any]:
    text = (body or "").strip()[:MAX_BODY]
    upload = file if file is not None and (file.filename or "") else None
    if not text and not upload:
        raise HTTPException(status_code=422, detail="Write a message or attach a file")
    stored = None
    if upload:
        ext = Path(upload.filename).suffix.lower()
        if ext not in ALLOWED:
            raise HTTPException(status_code=422, detail="Attach a PDF, Word, Excel, PowerPoint, CSV, text or image file")
        data = await upload.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Files can be at most {MAX_UPLOAD_MB} MB")
        if not data:
            raise HTTPException(status_code=422, detail="The file is empty")
        CHAT_DIR.mkdir(parents=True, exist_ok=True)
        stored = f"{secrets.token_hex(12)}{ext}"
        (CHAT_DIR / stored).write_bytes(data)
        safe_name = re.sub(r"[^\w .()-]", "_", Path(upload.filename).name)[:160]
    with get_conn() as conn:
        with conn.cursor() as cur:
            founder_id, staff_id = _pair(cur, user, other_id)
            cur.execute(
                """
                INSERT INTO chat_messages (founder_id, staff_id, sender_id, body, file_name, file_path, file_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, created_at
                """, (founder_id, staff_id, user["id"], text or None, safe_name if stored else None, stored, len(data) if stored else None))
            mid, at = cur.fetchone()
        conn.commit()
    return {"id": mid, "at": iso(at)}


@router.get("/file/{message_id}")
def chat_file(message_id: int, user: dict = Depends(auth_session)) -> FileResponse:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT founder_id, staff_id, file_name, file_path FROM chat_messages WHERE id = %s", (message_id,))
            row = cur.fetchone()
            if not row or not row[3]:
                raise HTTPException(status_code=404, detail="File not found")
            if user["id"] not in (row[0], row[1]):
                raise HTTPException(status_code=403, detail="This file is not in one of your conversations")
    path = (CHAT_DIR / row[3]).resolve()
    if CHAT_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=row[2])
