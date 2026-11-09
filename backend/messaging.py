"""Messages to founders and staff (meeting of 23 Oct 2026: email, WhatsApp links, preview before sending).

Every email goes into the email_outbox table first and is then delivered by SMTP in the background. Without
SMTP settings (backend/.env SMTP_*) a message is kept as "not sent" (test mode), and the workspace offers
"Copy", "Open in email app" and "Send on WhatsApp" for it instead. WhatsApp uses click-to-chat links
(https://wa.me/...), which need no account or third-party service.

Sign-in links: an invite (set a first password) or a reset is a single-use random token; only its SHA-256
hash is stored, it expires, and using it ends every other session of that account.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import smtplib
import ssl
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

from backend.config import PORTAL_URL, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_STARTTLS, SMTP_USER
from backend.db import get_conn

INVITE_DAYS = 14
RESET_DAYS = 3
NOT_CONFIGURED = "Email is not set up yet (test mode). Copy the message, open it in your email app or send it on WhatsApp."


def email_configured() -> bool:
    return bool(SMTP_HOST)


# ---------------------------------------------------------------- outbox
def queue_email(cur, to_email: str, to_name: str | None, subject: str, body: str, kind: str, created_by: str | None,
                company_id: int | None = None, to_phone: str | None = None) -> int:
    cur.execute(
        """
        INSERT INTO email_outbox (to_email, to_name, to_phone, subject, body, kind, company_id, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (to_email.strip().lower(), to_name, to_phone, subject[:300], body, kind, company_id, created_by),
    )
    return cur.fetchone()[0]


def _send_one(to_email: str, to_name: str | None, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = formataddr((to_name or "", to_email))
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="example.org")
    msg.set_content(body)
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=ssl.create_default_context()) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        return
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        if SMTP_STARTTLS:
            s.starttls(context=ssl.create_default_context())
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


def deliver(ids: list[int]) -> None:
    """Deliver queued messages now (called in a background thread after the request has committed)."""
    if not ids:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, to_email, to_name, subject, body FROM email_outbox WHERE id = ANY(%s) AND status IN ('queued', 'failed', 'not_sent')",
                (ids,),
            )
            rows = cur.fetchall()
            for mid, to_email, to_name, subject, body in rows:
                if not email_configured():
                    cur.execute("UPDATE email_outbox SET status = 'not_sent', error = %s WHERE id = %s", (NOT_CONFIGURED, mid))
                    continue
                try:
                    _send_one(to_email, to_name, subject, body)
                    cur.execute("UPDATE email_outbox SET status = 'sent', error = NULL, sent_at = NOW(), attempts = attempts + 1 WHERE id = %s", (mid,))
                except Exception as e:  # noqa: BLE001, record the failure; staff can retry from the outbox
                    cur.execute("UPDATE email_outbox SET status = 'failed', error = %s, attempts = attempts + 1 WHERE id = %s",
                                (f"{type(e).__name__}: {e}"[:400], mid))
        conn.commit()


def deliver_later(ids: list[int]) -> None:
    if ids:
        threading.Thread(target=deliver, args=(list(ids),), daemon=True).start()


def outbox_status(cur, ids: list[int]) -> list[dict[str, Any]]:
    cur.execute("SELECT id, status, error FROM email_outbox WHERE id = ANY(%s)", (ids,))
    return [{"id": r[0], "status": r[1], "error": r[2]} for r in cur.fetchall()]


# ---------------------------------------------------------------- WhatsApp click-to-chat
def whatsapp_url(phone: str | None, text: str) -> str:
    """https://wa.me/<number>?text=... (opens WhatsApp with the message ready). Indian 10-digit numbers get +91.
    Without a number WhatsApp asks which chat to send it to."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif digits.startswith("0") and len(digits) == 11:
        digits = "91" + digits[1:]
    base = f"https://wa.me/{digits}" if len(digits) >= 11 else "https://wa.me/"
    return f"{base}?text={urllib.parse.quote(text)}"


def mailto_url(to_email: str, subject: str, body: str) -> str:
    return f"mailto:{urllib.parse.quote(to_email)}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"


# ---------------------------------------------------------------- sign-in links
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_token(cur, user_id: int, purpose: str, created_by: str | None) -> str:
    """A new single-use link token; earlier unused links of the same purpose stop working."""
    token = secrets.token_urlsafe(32)
    days = INVITE_DAYS if purpose == "invite" else RESET_DAYS
    cur.execute("UPDATE account_tokens SET used_at = NOW() WHERE user_id = %s AND purpose = %s AND used_at IS NULL",
                (user_id, purpose))
    cur.execute(
        "INSERT INTO account_tokens (user_id, token_hash, purpose, expires_at, created_by) VALUES (%s, %s, %s, %s, %s)",
        (user_id, _hash(token), purpose, datetime.now(timezone.utc) + timedelta(days=days), created_by),
    )
    return token


def find_token(cur, token: str) -> tuple | None:
    """(token id, user id, purpose, email, full name, company name) for a valid, unused, unexpired link."""
    cur.execute(
        """
        SELECT t.id, u.id, t.purpose, u.email, u.full_name, c.name
        FROM account_tokens t JOIN users u ON u.id = t.user_id LEFT JOIN companies c ON c.id = u.company_id
        WHERE t.token_hash = %s AND t.used_at IS NULL AND t.expires_at > NOW() AND u.active
        """,
        (_hash(token),),
    )
    return cur.fetchone()


def link(purpose: str, token: str) -> str:
    return f"{PORTAL_URL}/?{'invite' if purpose == 'invite' else 'reset'}={token}"


# ---------------------------------------------------------------- message wording (plain text)
SIGN_OFF = "Warm regards,\nThe Demo Ventures team\n\nDemo Ventures Founder's Resource Portal · for Demo Ventures portfolio companies"


def invite_message(name: str, company: str, sender: str, url: str, note: str | None = None) -> tuple[str, str, str]:
    first = (name or "").split(" ")[0] or "there"
    subject = f"Your invitation to the Demo Ventures Founder's Resource Portal ({company})"
    body = (
        f"Hi {first},\n\n"
        f"{sender} has invited you to the Demo Ventures Founder's Resource Portal for {company}.\n\n"
        "In one place you get templates and guides picked for your stage and sector, sector updates, events, "
        "the 100-Day Playbook, introductions to vetted partners, and a direct line to your Demo Ventures team.\n\n"
        + (f"A note from {sender}: {note.strip()}\n\n" if note and note.strip() else "")
        + f"Set your password and sign in here (the link works once and expires in {INVITE_DAYS} days):\n{url}\n\n"
        + "The link is personal: please do not forward it.\n\n"
        + SIGN_OFF
    )
    wa = (f"Hi {first}, {sender} from Demo Ventures here. Your invitation to the Demo Ventures Founder's Resource Portal for {company} "
          f"is ready. Set your password here (works once, valid {INVITE_DAYS} days): {url}")
    return subject, body, wa


def reset_message(name: str, sender: str, url: str) -> tuple[str, str, str]:
    first = (name or "").split(" ")[0] or "there"
    subject = "Reset your Demo Ventures Founder's Resource Portal password"
    body = (f"Hi {first},\n\nA new password was requested for your Demo Ventures Founder's Resource Portal account"
            f"{f' by {sender}' if sender else ''}.\n\nChoose a new password here (the link works once and expires in "
            f"{RESET_DAYS} days):\n{url}\n\nIf you did not ask for this, you can ignore this email.\n\n{SIGN_OFF}")
    wa = f"Hi {first}, here is your link to set a new Demo Ventures portal password (works once, valid {RESET_DAYS} days): {url}"
    return subject, body, wa


def portal_link(page: str = "") -> str:
    return f"{PORTAL_URL}/{('#' + page) if page else ''}"


def workspace_link(tab: str = "") -> str:
    return f"{PORTAL_URL}/analyst.html{('#' + tab) if tab else ''}"


def company_team(cur, company_id: int) -> list[tuple[str, str, str | None]]:
    """(email, name, phone) of the company's current relationship manager and portfolio analyst."""
    cur.execute(
        """
        SELECT DISTINCT u.email, u.full_name, u.phone FROM (
            SELECT DISTINCT ON (role) user_id FROM company_assignments WHERE company_id = %s
            ORDER BY role, effective_from DESC, id DESC) a
        JOIN users u ON u.id = a.user_id WHERE u.active
        """,
        (company_id,),
    )
    return cur.fetchall()


def company_founders(cur, company_id: int) -> list[tuple[str, str, str | None]]:
    cur.execute("SELECT email, full_name, phone FROM users WHERE company_id = %s AND account_type = 'founder' AND active ORDER BY full_name",
                (company_id,))
    return cur.fetchall()


def notify(cur, people: list[tuple[str, str, str | None]], subject: str, body: str, kind: str, created_by: str | None,
           company_id: int | None) -> list[int]:
    """Queue one personal email per person (deliver_later() after the commit)."""
    ids = []
    for email, name, phone in people:
        first = (name or "").split(" ")[0] or "there"
        ids.append(queue_email(cur, email, name, subject, f"Hi {first},\n\n{body.strip()}\n\n{SIGN_OFF}", kind, created_by,
                               company_id, phone))
    return ids
