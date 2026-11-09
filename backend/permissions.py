"""Roles and permissions: the single source of truth.

Three staff tiers, plus founders:
  Tier 1  Super Admin  exactly one person; the whole portfolio, approvals, accounts, the full audit trail.
                       Moved to someone else only with the hand-over (POST /api/admin/super-admin/handover).
  Tier 2  Admin        portfolio managers; their own portfolio companies, their founders and analysts.
  Tier 3  Analyst      each portfolio team member; day-to-day founder support for their companies.
          Founder      invited founders, their own company's portal only.

Everything a non-Super-Admin adds (resources, events, Connect profiles, sector updates) waits for the
Super Admin's approval before founders see it.

The tables roles, permissions and role_permissions are rebuilt from this file at API start-up and by
the seed script, so docs/FEATURES.md, this file and the database cannot drift
apart. To change who can do what, edit ROLES below and restart the API.

Every API route checks a permission (never a role name) with security.need(...) or security.require_perm(...).
A grant is for all companies ("all") or only for companies the person is assigned to ("assigned").
Each permission has a plain-language label; the screens show the label, never the code.
"""
from __future__ import annotations

# code -> (label shown on screens, description)
PERMISSIONS: dict[str, tuple[str, str]] = {
    "overview.view": ("View overview", "See the workspace overview"),
    "companies.view": ("View companies", "See portfolio companies, their founders and Demo Ventures team"),
    "companies.add": ("Set up companies", "Add a portfolio company and edit the details of your companies"),
    "founders.manage": ("Manage founder accounts", "Invite founders and reset or deactivate their accounts"),
    "team.assign": ("Assign the Demo Ventures team", "Choose the company's relationship manager and analyst"),
    "staff.manage": ("Manage analysts", "Add analysts and reset or deactivate their accounts"),
    "admins.manage": ("Manage admins", "Add admins and move people between the Admin and Analyst tiers"),
    "super_admin.handover": ("Hand over Super Admin", "Give the Super Admin role to another person"),
    "audit.view": ("View audit trail", "See every admin change and every download"),
    "activity.founders": ("Track founder activity", "See what founders have done: sign-ins, downloads, requests"),
    "activity.analysts": ("Track analyst activity", "See what analysts have done"),
    "activity.admins": ("Track admin activity", "See what admins have done"),
    "content.submit": ("Add and edit content", "Add or edit resources, events, Connect profiles and sector updates"),
    "content.approve": ("Approve content", "Approve, return or withdraw anything waiting for approval"),
    "playbooks.manage": ("Manage playbooks", "Set the playbook owner and manage playbook tasks"),
    "news.publish": ("Write sector updates", "Write sector updates for a company"),
    "news.sources": ("Manage news feeds", "Add, pause and tag news feeds (used by beta news suggestions)"),
    "news.sources.approve": ("Approve news feeds", "Approve a news feed as a trusted source"),
    "events.manage": ("Manage events", "Add, cancel and restore events; add join and recording links"),
    "connect.manage": ("Manage Connect profiles", "Add, edit and hide Connect profiles"),
    "requests.handle": ("Handle founder requests", "Work queue: status, owner and priority"),
    "talent.feature": ("Feature candidate profiles", "Add a company's open roles and feature candidate profiles on its founders' dashboard"),
    "lms.manage": ("Manage the playbook lessons", "Write, order and publish the chapters and lessons founders see in the Playbook"),
    "talent.approve": ("Approve candidate profiles", "Decide whether a candidate profile is good enough to show to founders"),
    "intakes.view": ("Read questionnaire answers", "Read founders' questionnaire answers"),
    "founder.preview": ("Preview founder portal", "View the founder portal as one of your companies"),
    "portal.use": ("Use founder portal", "Use the founder portal for your own company"),
}

ALL = "all"
ASSIGNED = "assigned"  # only companies where the person is the current relationship manager or portfolio analyst


def _grants(all_: tuple[str, ...] = (), assigned: tuple[str, ...] = ()) -> dict[str, str]:
    return {**{p: ALL for p in all_}, **{p: ASSIGNED for p in assigned}}


# role code -> (display name, is staff role, tier (1 = highest), {permission: scope})
ROLES: dict[str, tuple[str, bool, int, dict[str, str]]] = {
    "super_admin": ("Super Admin", True, 1, {p: ALL for p in PERMISSIONS if p != "portal.use"}),
    "admin": ("Admin", True, 2, _grants(
        all_=("overview.view", "staff.manage", "content.submit", "news.publish", "news.sources", "events.manage",
              "connect.manage", "talent.approve", "lms.manage"),
        assigned=("companies.view", "companies.add", "founders.manage", "team.assign", "audit.view", "activity.founders",
                  "activity.analysts", "playbooks.manage", "intakes.view", "founder.preview", "requests.handle", "talent.feature"),
    )),
    "analyst": ("Analyst", True, 3, _grants(
        all_=("overview.view", "content.submit", "news.publish", "news.sources", "events.manage", "connect.manage"),
        assigned=("companies.view", "companies.add", "founders.manage", "activity.founders", "playbooks.manage",
                  "intakes.view", "founder.preview", "requests.handle", "talent.feature"),
    )),
    "founder": ("Founder", False, 9, {"portal.use": ALL}),
}

SUPER_ADMIN = "super_admin"
STAFF_LEVELS = ("admin", "analyst")  # tiers a person can be added to or moved between (Super Admin is handed over)

# Roles used before the three-tier model, mapped to their replacement when the API starts.
RETIRED_ROLES = {"content_admin": "analyst", "media_admin": "analyst", "agency_admin": "analyst"}

# Workspace sections and the permissions that show them (any one is enough). Mirrored in analyst.html.
WORKSPACE_TABS: dict[str, tuple[str, ...]] = {
    "overview": ("overview.view",),
    "approvals": ("content.approve",),
    "companies": ("companies.view",),
    "queue": ("requests.handle",),
    "intakes": ("intakes.view",),
    "activity": ("activity.founders", "activity.analysts", "activity.admins"),
    "content": ("content.submit", "content.approve"),
    "updates": ("news.publish",),
    "events": ("events.manage",),
    "connect": ("connect.manage",),
    "hiring": ("talent.feature", "talent.approve"),
    "messages": ("overview.view",),
    "course": ("lms.manage", "companies.view"),
    "team": ("staff.manage", "admins.manage", "super_admin.handover", "audit.view"),
}


def label(code: str) -> str:
    return PERMISSIONS[code][0] if code in PERMISSIONS else code


def sync_access_model(cur) -> None:
    """Rebuild roles, permissions and role_permissions from this file (idempotent)."""
    for code, (lbl, desc) in PERMISSIONS.items():
        cur.execute(
            "INSERT INTO permissions (code, description) VALUES (%s, %s) "
            "ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description",
            (code, f"{lbl}: {desc}"),
        )
    for code, (name, staff, _, _) in ROLES.items():
        cur.execute(
            "INSERT INTO roles (code, name, staff) VALUES (%s, %s, %s) "
            "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, staff = EXCLUDED.staff",
            (code, name, staff),
        )
    # People holding a retired role keep working, as the role that replaced it.
    for old, new in RETIRED_ROLES.items():
        cur.execute(
            "INSERT INTO user_roles (user_id, role_code, granted_by) "
            "SELECT user_id, %s, 'tier migration' FROM user_roles WHERE role_code = %s ON CONFLICT DO NOTHING",
            (new, old),
        )
        cur.execute("DELETE FROM user_roles WHERE role_code = %s", (old,))
    cur.execute("DELETE FROM role_permissions")
    for code, (_, _, _, grants) in ROLES.items():
        for perm, scope in grants.items():
            cur.execute(
                "INSERT INTO role_permissions (role_code, permission_code, scope) VALUES (%s, %s, %s)",
                (code, perm, scope),
            )
    cur.execute("DELETE FROM permissions WHERE code <> ALL(%s)", (list(PERMISSIONS),))
    cur.execute(
        "DELETE FROM roles r WHERE r.code <> ALL(%s) AND NOT EXISTS (SELECT 1 FROM user_roles u WHERE u.role_code = r.code)",
        (list(ROLES),),
    )
