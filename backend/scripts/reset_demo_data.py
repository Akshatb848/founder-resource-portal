"""Wipe demo activity so a stakeholder demo starts clean. LOCAL DEMO/TEST DATABASES ONLY.

Refuses to run on a database marked as real data (backend/data_mode.py), because it deletes accounts,
uploads, events, Connect profiles, requests and the audit trail.

Removes founder requests, work items, intake answers, download history, sessions, login
failures, analyst uploads, admin-published sector updates, the admin audit trail and any
smoke-test companies or accounts, RSVPs, read states, admin-created events and Connect profiles, and
restores catalog resources, starter playbook tasks, sample events and the Connect directory.
Real users, companies, team assignments, Connect entries and playbooks are kept.

    python backend/scripts/reset_demo_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.alpha_catalog import CATALOG  # noqa: E402
from backend.config import POSTGRES_CONFIG, UPLOAD_DIR  # noqa: E402
from backend.data_mode import TEST_DB, refuse_if_real  # noqa: E402
from backend.db import get_conn  # noqa: E402
from backend.seed import SUPER_ADMIN_EMAIL, seed  # noqa: E402
from backend.seed_portfolio import PORTFOLIO, TEAM  # noqa: E402

SEEDED_EMAILS = {SUPER_ADMIN_EMAIL, "riya@nimbus.demo", "analyst@team.demo", "manager@team.demo", *TEAM,
                 *(email for company in PORTFOLIO.values() for _, email in company[6])}


def main() -> None:
    if POSTGRES_CONFIG["host"] not in ("127.0.0.1", "localhost") or POSTGRES_CONFIG["dbname"] not in ("founder_portal_local", TEST_DB):
        raise SystemExit(f"Refusing to reset: this script only runs against a local database (founder_portal_local or {TEST_DB}).")
    with get_conn() as conn:
        with conn.cursor() as cur:
            refuse_if_real(cur, "reset demo data")
            cur.execute("SELECT file_name FROM resources WHERE slug LIKE 'upload-%'")
            uploads = [r[0] for r in cur.fetchall() if r[0]]
            for table in ("work_items", "founder_help", "founder_intake", "resource_downloads", "user_sessions", "login_failures",
                          "admin_audit", "event_rsvps", "notification_reads", "playbook_tasks", "sign_ins", "company_notes", "talent_profiles", "hiring_roles"):
                cur.execute(f"DELETE FROM {table}")
            # Smoke-test companies and accounts use a reserved slug prefix and email domain.
            cur.execute("DELETE FROM users WHERE email LIKE %s", ("%@smoke.team.demo",))
            # Accounts invited during a demo are removed; seeded accounts stay.
            cur.execute(
                "DELETE FROM users WHERE NOT (email = ANY(%s)) AND id NOT IN (SELECT user_id FROM user_roles WHERE role_code = 'super_admin')",
                (sorted(SEEDED_EMAILS),),
            )
            cur.execute("SELECT id FROM companies WHERE slug LIKE %s", ("smoke-%",))
            smoke = [row[0] for row in cur.fetchall()]
            for table in ("sector_updates", "playbook_progress", "company_assignments", "resources"):
                cur.execute(f"DELETE FROM {table} WHERE company_id = ANY(%s)", (smoke,))
            cur.execute("DELETE FROM companies WHERE id = ANY(%s)", (smoke,))
            # Hand-typed admin briefs are demo activity; news published from approved feeds is real and stays.
            cur.execute("DELETE FROM sector_updates WHERE published_by IS NOT NULL AND news_item_id IS NULL")
            # Admin-created events and Connect profiles are demo activity; seeded samples are restored below.
            cur.execute("DELETE FROM events WHERE created_by IS NOT NULL")
            cur.execute("DELETE FROM connect_entries WHERE created_by IS NOT NULL")
            cur.execute("UPDATE events SET active = TRUE, recording_url = NULL, join_link = NULL, pending_join_link = NULL, "
                        "pending_recording_url = NULL, approval = 'approved' WHERE created_by IS NULL")
            cur.execute("UPDATE connect_entries SET active = TRUE WHERE created_by IS NULL")
            cur.execute("DELETE FROM resources WHERE slug LIKE 'upload-%'")
            cur.execute("UPDATE resources SET pending_changes = NULL, pending_file = NULL, pending_by = NULL, pending_at = NULL")
            cur.execute("UPDATE companies SET status = 'active'")
            for item in CATALOG:
                cur.execute(
                    "UPDATE resources SET status = %s, review_comment = NULL WHERE slug = %s",
                    (item["status"], item["slug"]),
                )
        conn.commit()
    for name in uploads:
        p = (UPLOAD_DIR / name).resolve()
        if p.is_file() and UPLOAD_DIR.resolve() in p.parents:
            p.unlink()
    seed()  # restore starter playbook tasks, sample events and the Connect directory
    print(f"Demo data reset ({len(uploads)} uploaded file(s) removed).")


if __name__ == "__main__":
    main()
