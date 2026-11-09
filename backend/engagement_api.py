"""Founder engagement API, events & RSVPs, 100-Day Playbook tasks, notifications, Connect directory.

Founders see only their own company's data; admin-side management lives in backend/admin_api.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.audience import visible
from backend.config import EVENTS_OFFICE_EMAIL
from backend.db import get_conn
from backend.messaging import company_team, deliver_later, notify, workspace_link
from backend.playbook import PHASES, sync_progress
from backend.security import auth_session, founder_company, iso, require_founder, require_founder_or_preview

IST = timezone(timedelta(hours=5, minutes=30))

router = APIRouter(prefix="/api/founder")


def founder_scope(user: dict = Depends(auth_session)) -> dict[str, Any]:
    """Founders (own company) or staff with founder.preview (the company they chose to preview)."""
    require_founder_or_preview(user)
    if not user.get("company_id"):
        cid, name = founder_company(user)
        user = {**user, "company_id": cid, "company_name": name}
    return user


# ---------------------------------------------------------------- events
class RsvpIn(BaseModel):
    going: bool


EVENT_COLS = """
    e.id, e.title, e.description, e.location, e.starts_at, e.ends_at, e.company_id, e.recording_url, e.is_sample,
    EXISTS (SELECT 1 FROM event_rsvps r WHERE r.event_id = e.id AND r.user_id = %s), e.join_link, e.rsvp_url
"""


def _event_row(r: tuple) -> dict[str, Any]:
    return {
        "id": r[0], "title": r[1], "description": r[2], "location": r[3], "starts_at": iso(r[4]), "ends_at": iso(r[5]),
        "audience": "Invited for your company" if r[6] else "Portfolio-wide", "recording_url": r[7], "is_sample": r[8],
        "going": r[9], "past": (r[5] or r[4]) < datetime.now(timezone.utc),
        "join_link": r[10] if r[10] and r[10].startswith(("https://", "http://")) else None,
        "meeting_id": r[10] if r[10] and not r[10].startswith(("https://", "http://")) else None,
        "rsvp_url": r[11] or None,
    }


@router.get("/events")
def list_events(user: dict = Depends(founder_scope)) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {EVENT_COLS} FROM events e
                WHERE e.active AND e.approval = 'approved' AND {visible('e')}
                  AND (e.starts_at > NOW() - INTERVAL '180 days')
                ORDER BY e.starts_at
                """,
                (user["id"], user["company_id"]),
            )
            return [_event_row(r) for r in cur.fetchall()]


@router.post("/events/{event_id}/rsvp")
def rsvp(event_id: int, body: RsvpIn, user: dict = Depends(founder_scope)) -> dict[str, Any]:
    require_founder(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT starts_at, title, location, rsvp_url, created_by FROM events WHERE id = %s AND active AND approval = 'approved' AND {visible()}",
                (event_id, user["company_id"]),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Event not found")
            starts, title, location, rsvp_url, created_by = row
            if starts < datetime.now(timezone.utc):
                raise HTTPException(status_code=422, detail="This event has already started")
            if rsvp_url:
                raise HTTPException(status_code=422, detail="RSVP for this event on its own page")
            cur.execute("SELECT 1 FROM event_rsvps WHERE event_id = %s AND user_id = %s", (event_id, user["id"]))
            was_going = bool(cur.fetchone())
            if body.going:
                cur.execute(
                    "INSERT INTO event_rsvps (event_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (event_id, user["id"]),
                )
            else:
                cur.execute("DELETE FROM event_rsvps WHERE event_id = %s AND user_id = %s", (event_id, user["id"]))
            ids = _rsvp_emails(cur, user, title, location, starts, created_by, body.going) if body.going != was_going else []
        conn.commit()
    deliver_later(ids)
    return {"event_id": event_id, "going": body.going}


def _rsvp_emails(cur, user: dict[str, Any], title: str, location: str | None, starts: datetime, created_by: str | None,
                 going: bool) -> list[int]:
    """An internal event's RSVP is an email to Demo Ventures: the event's organiser, the company's relationship manager
    and analyst, and the office inbox (EVENTS_OFFICE_EMAIL), once each."""
    people: dict[str, tuple[str, str, str | None]] = {}
    for email, name, phone in company_team(cur, user["company_id"]):
        people.setdefault(email.lower(), (email, name, phone))
    if created_by:
        cur.execute("SELECT email, full_name, phone FROM users WHERE full_name = %s AND account_type = 'staff' AND active", (created_by,))
        for email, name, phone in cur.fetchall():
            people.setdefault(email.lower(), (email, name, phone))
    if EVENTS_OFFICE_EMAIL:
        people.setdefault(EVENTS_OFFICE_EMAIL.lower(), (EVENTS_OFFICE_EMAIL, "Demo Ventures events team", None))
    when = starts.astimezone(IST).strftime("%a %d %b %Y, %I:%M %p").replace(" 0", " ") + " IST"
    founder = f"{user['full_name']} ({user.get('company_name') or 'portfolio founder'})"
    subject = f"RSVP: {founder} {'is attending' if going else 'can no longer attend'} {title}"
    body = (f"{founder} {'RSVPed to' if going else 'cancelled their RSVP for'} {title}.\n\nWhen: {when}\n"
            f"Where: {location or 'to be confirmed'}\nFounder's email: {user.get('email', '')}\n\n"
            f"See every RSVP in the workspace: {workspace_link('events')}")
    return notify(cur, list(people.values()), subject, body, "event.rsvp", user["full_name"], user["company_id"])


# ---------------------------------------------------------------- playbook
class TaskIn(BaseModel):
    done: bool


@router.get("/playbook")
def playbook(user: dict = Depends(founder_scope)) -> dict[str, Any]:
    cid = user["company_id"]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT playbook_name, progress_pct, current_phase, owner_name, updated_at FROM playbook_progress WHERE company_id = %s",
                (cid,),
            )
            pb = cur.fetchone()
            cur.execute(
                """
                SELECT t.id, t.phase_no, t.title, t.done, t.done_at, t.done_by, r.id, r.title
                FROM playbook_tasks t
                LEFT JOIN resources r ON r.slug = t.resource_slug AND r.status = 'approved'
                    AND (r.company_id IS NULL OR r.company_id = t.company_id)
                WHERE t.company_id = %s ORDER BY t.phase_no, t.sort_order, t.id
                """,
                (cid,),
            )
            tasks = cur.fetchall()
    phases = []
    for no, name, days in PHASES:
        items = [
            {"id": t[0], "title": t[2], "done": t[3], "done_at": iso(t[4]), "done_by": t[5], "resource_id": t[6], "resource_title": t[7]}
            for t in tasks if t[1] == no
        ]
        done = sum(1 for i in items if i["done"])
        status = "complete" if items and done == len(items) else ("active" if pb and pb[2].startswith(name) else "upcoming")
        phases.append({"no": no, "name": name, "days": days, "status": status, "done": done, "total": len(items), "tasks": items})
    if not pb:
        return {"playbook_name": "100-Day Founder Playbook", "progress_pct": 0, "current_phase": "", "owner_name": None, "phases": phases}
    return {
        "playbook_name": pb[0], "progress_pct": pb[1], "current_phase": pb[2], "owner_name": pb[3], "updated_at": iso(pb[4]),
        "phases": phases,
    }


@router.patch("/playbook/tasks/{task_id}")
def toggle_task(task_id: int, body: TaskIn, user: dict = Depends(founder_scope)) -> dict[str, Any]:
    require_founder(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT company_id FROM playbook_tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            if not row or row[0] != user["company_id"]:
                raise HTTPException(status_code=404, detail="Task not found")
            cur.execute(
                """
                UPDATE playbook_tasks SET done = %s, done_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                    done_by = CASE WHEN %s THEN %s ELSE NULL END
                WHERE id = %s
                """,
                (body.done, body.done, body.done, user["full_name"], task_id),
            )
            pct, phase = sync_progress(cur, user["company_id"])
        conn.commit()
    return {"task_id": task_id, "done": body.done, "progress_pct": pct, "current_phase": phase}


# ---------------------------------------------------------------- notifications
class ReadIn(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=50)
    all: bool = False


def _notification_items(cur, user: dict[str, Any]) -> list[dict[str, Any]]:
    cid = user["company_id"]
    items: list[dict[str, Any]] = []
    cur.execute(
        """
        SELECT h.public_ref, h.subject, h.founder_status, h.updated_at FROM founder_help h
        WHERE h.company_id = %s AND h.updated_at > h.created_at + INTERVAL '1 second'
        ORDER BY h.updated_at DESC LIMIT 5
        """,
        (cid,),
    )
    for ref, subject, status, at in cur.fetchall():
        items.append({"key": f"help:{ref}:{status}", "kind": "request", "title": "Update from Demo Ventures", "text": f"{subject} · {status}", "goto": "requests", "at": at})
    cur.execute(
        f"""
        SELECT id, label, title, published_at FROM sector_updates
        WHERE {visible()} AND approval = 'approved' AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY published_at DESC LIMIT 4
        """,
        (cid,),
    )
    for uid, label, title, at in cur.fetchall():
        items.append({"key": f"update:{uid}", "kind": "update", "title": title, "text": f"{(label or 'Update').title()} · sector update", "goto": "updates", "at": at})
    cur.execute(
        """
        SELECT id, title, reviewed_at FROM resources
        WHERE company_id = %s AND status = 'approved' AND placement = 'library' ORDER BY reviewed_at DESC NULLS LAST LIMIT 2
        """,
        (cid,),
    )
    for rid, title, at in cur.fetchall():
        items.append({"key": f"resource:{rid}", "kind": "resource", "title": f"Published for {user['company_name']}", "text": title, "goto": "resources", "at": at})
    cur.execute(
        f"""
        SELECT e.id, e.title, e.starts_at, e.created_at FROM events e
        WHERE e.active AND e.approval = 'approved' AND e.starts_at > NOW() AND e.starts_at < NOW() + INTERVAL '45 days'
          AND {visible('e')}
        ORDER BY e.starts_at LIMIT 3
        """,
        (cid,),
    )
    for eid, title, starts, created in cur.fetchall():
        when = starts.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b, %I:%M %p IST")
        items.append({"key": f"event:{eid}", "kind": "event", "title": f"Event: {title}", "text": when, "goto": "events", "at": created})
    items.sort(key=lambda i: i["at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:10]


@router.get("/notifications")
def notifications(user: dict = Depends(founder_scope)) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            items = _notification_items(cur, user)
            cur.execute("SELECT item_key FROM notification_reads WHERE user_id = %s", (user["id"],))
            read = {r[0] for r in cur.fetchall()}
    out = [{**i, "at": iso(i["at"]), "read": i["key"] in read} for i in items]
    return {"items": out, "unread": sum(1 for i in out if not i["read"])}


@router.post("/notifications/read")
def mark_read(body: ReadIn, user: dict = Depends(founder_scope)) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            keys = [i["key"] for i in _notification_items(cur, user)] if body.all else body.keys
            keys = [k for k in keys if 0 < len(k) <= 160][:50]
            for k in keys:
                cur.execute(
                    "INSERT INTO notification_reads (user_id, item_key) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user["id"], k),
                )
        conn.commit()
    return {"marked": len(keys)}


# ---------------------------------------------------------------- connect
@router.get("/connect")
def connect(user: dict = Depends(founder_scope)) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, network_group, subcategory, display_name, role_title, organization, skills, why_relevant,
                    category_tag, is_sample, website, stage, cheque_size
                FROM connect_entries WHERE active IS TRUE AND approval = 'approved' ORDER BY network_group, subcategory, display_name
                """
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "network_group": r[1], "subcategory": r[2], "display_name": r[3], "role_title": r[4],
         "organization": r[5], "skills": r[6] or [], "why_relevant": r[7], "category_tag": r[8], "is_sample": r[9],
         "website": r[10] or "", "stage": r[11] or "", "cheque_size": r[12] or ""}
        for r in rows
    ]
