"""Database-backed sessions (survives API restart; suitable for local alpha and VM deploy)."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.db import get_conn
from backend.sqlutil import q

SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "168"))


def _user_payload(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "email": row[1],
        "full_name": row[2],
        "account_type": row[3],
        "company_id": row[4],
        "company_name": row[5],
        "sector": row[6],
    }


def load_access(cur, user: dict[str, Any]) -> dict[str, Any]:
    """Add roles, permissions and per-permission scope ("all" or "assigned") to a user dict."""
    cur.execute(
        q(
            """
            SELECT ur.role_code, rp.permission_code, rp.scope
            FROM user_roles ur LEFT JOIN role_permissions rp ON rp.role_code = ur.role_code
            WHERE ur.user_id = %s
            """
        ),
        (user["id"],),
    )
    roles: set[str] = set()
    scope: dict[str, str] = {}
    for role, perm, sc in cur.fetchall():
        roles.add(role)
        if perm and scope.get(perm) != "all":
            scope[perm] = sc
    user["roles"] = sorted(roles)
    user["permissions"] = sorted(scope)
    user["assigned_only"] = sorted(p for p, sc in scope.items() if sc == "assigned")
    return user


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Multiple devices may be signed in at once; only expired sessions are cleared here.
            cur.execute(q("DELETE FROM user_sessions WHERE user_id = %s AND expires_at < NOW()"), (user_id,))
            cur.execute(
                q(
                    """
                    INSERT INTO user_sessions (token, user_id, expires_at)
                    VALUES (%s, %s, %s)
                    """
                ),
                (token, user_id, expires),
            )
        conn.commit()
    return token


def resolve_session(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q(
                    """
                    SELECT u.id, u.email, u.full_name, u.account_type, u.company_id,
                           c.name, c.sector, s.expires_at
                    FROM user_sessions s
                    JOIN users u ON u.id = s.user_id
                    LEFT JOIN companies c ON c.id = u.company_id
                    WHERE s.token = %s AND u.active IS TRUE
                    """
                ),
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            expires = row[7]
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < now:
                cur.execute(q("DELETE FROM user_sessions WHERE token = %s"), (token,))
                conn.commit()
                return None
            return load_access(cur, _user_payload(row[:7]))


def revoke_session(token: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(q("DELETE FROM user_sessions WHERE token = %s"), (token,))
        conn.commit()
