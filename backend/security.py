"""Shared request guards and helpers used by every API module.

Access is decided by permissions (backend/permissions.py), never by role names:
    user: dict = Depends(need("content.approve"))      # route needs this permission
    require_perm(user, "news.publish", "content.submit")  # any one of these
    company_scope(user, "companies.view")               # None = all companies, else the assigned ids
    founder_company(user)                               # the company a founder screen is about
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException

from backend.auth_store import resolve_session
from backend.db import get_conn

# Staff previewing the founder portal send X-Preview-Company: <company id>; main.py's middleware stores it here.
preview_request: ContextVar[int | None] = ContextVar("preview_request", default=None)


def auth_session(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing session")
    token = authorization.removeprefix("Bearer ").strip()
    user = resolve_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


def has_perm(user: dict[str, Any], *perms: str) -> bool:
    granted = user.get("permissions") or ()
    return any(p in granted for p in perms)


def require_perm(user: dict[str, Any], *perms: str) -> None:
    """Allow the request if the user holds any one of the permissions."""
    if not has_perm(user, *perms):
        raise HTTPException(status_code=403, detail="You do not have permission to do this")


def need(*perms: str) -> Callable[..., dict[str, Any]]:
    """FastAPI dependency: a signed-in user holding any one of the permissions."""

    def dependency(user: dict = Depends(auth_session)) -> dict[str, Any]:
        require_perm(user, *perms)
        return user

    return dependency


def is_founder(user: dict[str, Any]) -> bool:
    return user.get("account_type") == "founder" and has_perm(user, "portal.use")


def require_founder_or_preview(user: dict[str, Any]) -> None:
    """Founder portal reads: founders (own company) or staff allowed to preview it."""
    if not (is_founder(user) or has_perm(user, "founder.preview")):
        raise HTTPException(status_code=403, detail="You do not have permission to do this")


def require_founder(user: dict[str, Any]) -> None:
    """Founder portal actions (RSVP, tick a task, ask for help) are for founders only."""
    if not is_founder(user):
        raise HTTPException(status_code=403, detail="Only founders can do this")


def _current_assignments() -> list[tuple[int, int | None]]:
    """(company_id, staff user_id) for each company's current relationship manager and analyst."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (company_id, role) company_id, user_id FROM company_assignments
                ORDER BY company_id, role, effective_from DESC, id DESC
                """
            )
            return cur.fetchall()


def direct_reports(user_id: int) -> set[int]:
    """Analysts who report to this Admin."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE reports_to = %s AND account_type = 'staff'", (user_id,))
            return {r[0] for r in cur.fetchall()}


def company_scope(user: dict[str, Any], perm: str) -> set[int] | None:
    """None if the permission covers all companies; otherwise the companies the user is assigned to
    (relationship manager or portfolio analyst) plus those of the analysts who report to them, so an
    Admin can always do what their analysts can, on the same companies."""
    if perm not in (user.get("assigned_only") or ()):
        return None
    people = {user["id"]} | direct_reports(user["id"])
    return {cid for cid, uid in _current_assignments() if uid in people}


def colleague_ids(user: dict[str, Any], perm: str) -> set[int] | None:
    """Staff the user may track: None = everyone; otherwise their direct reports and the people
    assigned to the user's companies."""
    companies = company_scope(user, perm)
    if companies is None:
        return None
    return {uid for cid, uid in _current_assignments() if cid in companies and uid} | direct_reports(user["id"])


def require_company(user: dict[str, Any], perm: str, company_id: int) -> None:
    require_perm(user, perm)
    allowed = company_scope(user, perm)
    if allowed is not None and company_id not in allowed:
        raise HTTPException(status_code=403, detail="You are not assigned to this company")


def founder_company(user: dict[str, Any]) -> tuple[int, str]:
    """The company a founder-portal request is about: the founder's own, or, for staff with
    founder.preview, the company they chose to preview (default: the first one they may see)."""
    if user.get("company_id"):
        return int(user["company_id"]), user.get("company_name") or ""
    require_founder_or_preview(user)
    allowed = company_scope(user, "founder.preview")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, slug FROM companies ORDER BY name")
            companies = [r for r in cur.fetchall() if allowed is None or r[0] in allowed]
    if not companies:
        raise HTTPException(status_code=403, detail="You have no assigned company to preview")
    wanted = preview_request.get()
    for cid, name, _ in companies:
        if cid == wanted:
            return cid, name
    pilot = next((c for c in companies if c[2] == "nimbus-mobility"), companies[0])
    return pilot[0], pilot[1]


def iso(val: Any) -> str | None:
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)
