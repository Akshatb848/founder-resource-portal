"""Sign in with a one-time code sent by email (alpha-v1.2.6, 30 Oct 2026). Switched off by default.

    GET  /api/auth/options        (public) which sign-in methods the page should offer
    POST /api/auth/otp/request    (public) email a 6-digit code; same answer whether or not the email has an account
    POST /api/auth/otp/verify     (public) sign in with the code; same lock-out as password sign-in

While OTP_SIGNIN_ENABLED is off, the two /otp routes answer 404 and the sign-in page shows no code button.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.auth_store import create_session, load_access
from backend.config import LOGIN_LOCKOUT_MINUTES, LOGIN_MAX_FAILURES, OTP_MAX_ATTEMPTS, OTP_MINUTES
from backend import config
from backend.db import get_conn
from backend.messaging import SIGN_OFF, deliver_later, queue_email

router = APIRouter(prefix="/api")

CODES_PER_EMAIL = 3      # codes one email address can ask for in 15 minutes
CODES_PER_DEVICE = 10    # code requests one device can make in an hour (any email)
SENT = "If this email has an account, a sign-in code is on its way. It works once, for {m} minutes."


class OtpRequestIn(BaseModel):
    email: EmailStr


class OtpVerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


def _enabled() -> None:
    if not config.OTP_SIGNIN_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")


def _hash(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def otp_message(name: str | None, code: str) -> tuple[str, str]:
    first = (name or "").split(" ")[0] or "there"
    subject = f"{code} is your Demo Ventures portal sign-in code"
    body = (f"Hi {first},\n\nYour code to sign in to the Demo Ventures Founder's Resource Portal is:\n\n    {code}\n\n"
            f"It works once and expires in {OTP_MINUTES} minutes. Never share it: the Demo Ventures team will not ask "
            f"you for it.\n\nIf you did not ask for this code, you can ignore this email.\n\n{SIGN_OFF}")
    return subject, body


@router.get("/auth/options")
def sign_in_options() -> dict[str, Any]:
    return {"password": True, "otp": config.OTP_SIGNIN_ENABLED, "google": False}


@router.post("/auth/otp/request")
def otp_request(body: OtpRequestIn, request: Request) -> dict[str, str]:
    _enabled()
    email = body.email.lower()
    client = request.client.host if request.client else "unknown"
    ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('login_codes'))")
            cur.execute("DELETE FROM login_codes WHERE created_at < NOW() - INTERVAL '1 day'")
            cur.execute("DELETE FROM public_form_hits WHERE client = %s AND created_at < NOW() - INTERVAL '1 day'", (f"otp:{client}",))
            # Every request counts against the device, with or without an account, so the answer never reveals one.
            cur.execute("SELECT COUNT(*) FROM public_form_hits WHERE client = %s AND created_at > NOW() - INTERVAL '1 hour'",
                        (f"otp:{client}",))
            if cur.fetchone()[0] >= CODES_PER_DEVICE:
                raise HTTPException(status_code=429, detail="Too many codes asked for from this device. Try again in an hour.")
            cur.execute("INSERT INTO public_form_hits (client) VALUES (%s)", (f"otp:{client}",))
            cur.execute("SELECT id, full_name, company_id, phone FROM users WHERE email = %s AND active", (email,))
            row = cur.fetchone()
            if row:
                cur.execute("SELECT COUNT(*) FROM login_codes WHERE user_id = %s AND created_at > NOW() - INTERVAL '15 minutes'",
                            (row[0],))
                if cur.fetchone()[0] < CODES_PER_EMAIL:
                    code = f"{secrets.randbelow(1_000_000):06d}"
                    # A new code replaces any earlier one that was not used.
                    cur.execute("UPDATE login_codes SET used_at = NOW() WHERE user_id = %s AND used_at IS NULL", (row[0],))
                    cur.execute(
                        "INSERT INTO login_codes (user_id, code_hash, client, expires_at) VALUES (%s, %s, %s, %s)",
                        (row[0], _hash(row[0], code), client, datetime.now(timezone.utc) + timedelta(minutes=OTP_MINUTES)),
                    )
                    subject, text = otp_message(row[1], code)
                    ids.append(queue_email(cur, email, row[1], subject, text, "otp", "self-service", row[2], row[3]))
        conn.commit()
    deliver_later(ids)
    return {"status": SENT.format(m=OTP_MINUTES)}


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerifyIn, request: Request) -> dict[str, Any]:
    _enabled()
    email = body.email.lower()
    client = request.client.host if request.client else "unknown"
    since = datetime.now(timezone.utc) - timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM login_failures WHERE email = %s AND COALESCE(client, '') = %s AND created_at > %s",
                        (email, client, since))
            if cur.fetchone()[0] >= LOGIN_MAX_FAILURES:
                raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {LOGIN_LOCKOUT_MINUTES} minutes.")
            cur.execute(
                """
                SELECT u.id, u.email, u.full_name, u.account_type, u.company_id, c.name, c.sector, lc.id, lc.code_hash
                FROM users u
                LEFT JOIN companies c ON c.id = u.company_id
                LEFT JOIN LATERAL (
                    SELECT id, code_hash FROM login_codes
                    WHERE user_id = u.id AND used_at IS NULL AND expires_at > NOW() AND attempts < %s
                    ORDER BY created_at DESC LIMIT 1
                ) lc ON TRUE
                WHERE u.email = %s AND u.active IS TRUE
                """,
                (OTP_MAX_ATTEMPTS, email),
            )
            row = cur.fetchone()
            ok = bool(row and row[7] and hmac.compare_digest(row[8], _hash(row[0], body.code)))
            if not ok:
                if row and row[7]:
                    cur.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id = %s", (row[7],))
                cur.execute("INSERT INTO login_failures (email, client) VALUES (%s, %s)", (email, client))
                cur.execute(
                    "INSERT INTO admin_audit (actor, action, target, details, company_id) VALUES (%s, 'login.failed', %s, %s, %s)",
                    (email, email, json.dumps({"device": client, "method": "code"}), row[4] if row else None),
                )
                conn.commit()
                raise HTTPException(status_code=401, detail="That code is wrong or has expired. Ask for a new one.")
            cur.execute("UPDATE login_codes SET used_at = NOW() WHERE id = %s", (row[7],))
            cur.execute("DELETE FROM login_failures WHERE email = %s AND COALESCE(client, '') = %s", (email, client))
            cur.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (row[0],))
            cur.execute("INSERT INTO sign_ins (user_id) VALUES (%s)", (row[0],))
            user = load_access(cur, {"id": row[0], "email": row[1], "full_name": row[2], "account_type": row[3],
                                     "company_id": row[4], "company_name": row[5], "sector": row[6]})
        conn.commit()
    if user["account_type"] == "founder" and not (user["company_id"] and "portal.use" in user["permissions"]):
        raise HTTPException(status_code=403, detail="This founder account is not linked to a company yet. Contact Demo Ventures.")
    if user["account_type"] == "staff" and not user["roles"]:
        raise HTTPException(status_code=403, detail="Your account has no role yet. Ask a Super Admin to assign one.")
    token = create_session(user["id"])
    return {"token": token, "user": user, "redirect": "/" if user["account_type"] == "founder" else "/analyst.html"}
