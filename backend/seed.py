"""Apply the database schema, and load demo data into demo/test databases.

    python -m backend.seed                # schema updates; demo data too, unless the database holds real data
    python -m backend.seed --schema-only  # schema updates only (what releases run on the main database)

Demo data is never loaded into a database marked as real (backend/data_mode.py). Seeding only adds what
is missing: it never changes an existing account's password or name, or a company's details.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.alpha_catalog import ALPHA_REVIEW_NOTE, CATALOG  # noqa: E402
from backend.data_mode import holds_real_data, refuse_if_real  # noqa: E402
from backend.lms_content import ensure_starter  # noqa: E402
from backend.db import get_conn  # noqa: E402
from backend.news_feed import seed_starter_sources  # noqa: E402
from backend.permissions import sync_access_model  # noqa: E402
from backend.playbook import seed_template_tasks, sync_progress  # noqa: E402
from backend.scripts.import_connects import apply_connects, load as load_connects  # noqa: E402
from backend.seed_portfolio import seed_portfolio  # noqa: E402
from backend.sqlutil import q  # noqa: E402


# The Connect directory is a fictional demo list, the same on every database:
# backend/data/demo_connects.json, loaded by backend/scripts/import_connects.py.

SAMPLE_EVENTS = [
    # (title, description, location, days from today, start hour IST, duration minutes, pilot company only, recording URL)
    ("Founder Day 2026", "Founder conversations, operator sessions and peer learning. Sample event, date to be confirmed.", "Gurugram · in person", 24, 10, 390, True, None),
    ("Finance Office Hours", "Open questions on reporting, finance controls and planning. Sample event.", "Online", 30, 16, 60, False, None),
    ("Series A Readiness Clinic", "A working session for founders preparing an institutional round. Sample event.", "Online", 45, 15, 90, False, None),
]



def upsert_user(cur, email: str, pw_hash: str, full_name: str, account_type: str, company_id: int | None,
                roles: list[str], granted_by: str = "seed") -> int:
    """Create a missing account and make sure it holds the given roles (extra roles are kept)."""
    cur.execute(
        q(
            """
            INSERT INTO users (email, password_hash, full_name, account_type, company_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            """
        ),
        (email, pw_hash, full_name, account_type, company_id),
    )
    # An existing account keeps its password and name: seeding only adds missing accounts.
    cur.execute(q("SELECT id FROM users WHERE email = %s"), (email,))
    uid = cur.fetchone()[0]
    for role in roles:
        cur.execute(
            q("INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"),
            (uid, role, granted_by),
        )
    return uid


def link_assignments_to_staff(cur) -> None:
    """Point team assignments at the staff account with the same name (used for analyst scoping)."""
    cur.execute(
        q(
            """
            UPDATE company_assignments a SET user_id = u.id
            FROM users u
            WHERE a.user_id IS NULL AND u.account_type = 'staff' AND u.active
              AND lower(trim(u.full_name)) = lower(trim(a.person))
            """
        )
    )


SUPER_ADMIN_EMAIL = "superadmin@team.demo"
# Demo accounts from the six-role version (21 Oct). Removed: the two-level model has no such roles.
RETIRED_DEMO_ACCOUNTS = ("admin@team.demo", "content@team.demo", "media@team.demo", "agency@team.demo")


def seed_super_admin(cur, pw_hash: str) -> None:
    """superadmin@team.demo is the one Super Admin on a new database. If the role was handed over
    (for example to Kavya Reddy), re-seeding keeps that person and the seeded account stays an Analyst."""
    cur.execute(
        q("SELECT u.email FROM user_roles r JOIN users u ON u.id = r.user_id WHERE r.role_code = 'super_admin'")
    )
    row = cur.fetchone()
    current = row[0] if row else None
    intern_id = upsert_user(cur, SUPER_ADMIN_EMAIL, pw_hash, "Neha Verma", "staff", None, [])
    if current is None or current in RETIRED_DEMO_ACCOUNTS:
        cur.execute(q("DELETE FROM user_roles WHERE role_code = 'super_admin'"))
        cur.execute(q("DELETE FROM user_roles WHERE user_id = %s"), (intern_id,))
        cur.execute(
            q("INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'super_admin', 'seed')"), (intern_id,)
        )
    elif current != SUPER_ADMIN_EMAIL:
        cur.execute(
            q("INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'analyst', 'seed') ON CONFLICT DO NOTHING"),
            (intern_id,),
        )
    cur.execute(q("SELECT id FROM users WHERE email = ANY(%s)"), (list(RETIRED_DEMO_ACCOUNTS),))
    retired = [r[0] for r in cur.fetchall()]
    if retired:
        cur.execute(q("DELETE FROM resource_downloads WHERE user_id = ANY(%s)"), (retired,))
        cur.execute(q("DELETE FROM users WHERE id = ANY(%s)"), (retired,))

def apply_schema() -> None:
    """Run schema.sql as one script (it contains DO $$ ... $$ blocks, so it is not split on ';'),
    then rebuild roles and permissions from backend/permissions.py."""
    raw = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(raw)
            sync_access_model(cur)
            ensure_starter(cur)  # the playbook course's starter chapters, only into an empty course
        conn.commit()



PILOT_NEWS_KEYWORDS = (
    "Nimbus Mobility, rapid charging, fast charging, battery pack, LFP, electric three-wheeler, "
    "electric commercial vehicle, e-3W, battery swapping, charging station, PM E-DRIVE, ACC PLI, BIS battery"
)

def seed_hiring_sample(cur, company_id: int) -> None:
    """One clearly labelled sample opening and featured profile for the pilot company (only when it has none)."""
    cur.execute("SELECT 1 FROM hiring_roles WHERE company_id = %s", (company_id,))
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO hiring_roles (company_id, title, seniority, location, notes, created_by_name, from_fund, is_sample)
        VALUES (%s, 'VP Engineering, battery systems (sample opening)', 'Leadership', 'Bengaluru',
            'Leads the battery pack and charger engineering teams. Sample opening for the alpha demo.',
            'Sara Thomas', TRUE, TRUE) RETURNING id
        """,
        (company_id,),
    )
    role_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM users WHERE email = 'analyst@team.demo'")
    analyst = cur.fetchone()
    cur.execute(
        """
        INSERT INTO talent_profiles (company_id, role_id, full_name, headline, experience_years, location, summary,
            fit_note, consent_confirmed, featured_by, featured_by_name, is_sample)
        VALUES (%s, %s, 'Aman Kulkarni (test)', 'Director of Engineering, battery management systems (test profile)',
            14, 'Bengaluru',
            'Test profile for the alpha demo: has led battery management and charging firmware teams of about 40 engineers through two vehicle launches.',
            'Sample note: experience scaling a battery engineering team matches the VP Engineering opening.',
            TRUE, %s, 'Sara Thomas', TRUE)
        """,
        (company_id, role_id, analyst[0] if analyst else None),
    )


def samples_wanted() -> bool:
    """Sample events, briefs and candidate profiles exist only on throw-away test copies (the automated tests
    use them). Dev and the replica show real content only (partner review, 4 Nov 2026)."""
    import os
    from backend.config import POSTGRES_CONFIG
    return str(POSTGRES_CONFIG.get("dbname", "")).endswith("_test") or os.getenv("PORTAL_SAMPLES") == "1"


def seed() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            refuse_if_real(cur, "load demo data")
    pw = bcrypt.hashpw(b"demo1234", bcrypt.gensalt()).decode()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            q(
                """
                INSERT INTO companies (slug, name, sector, stage)
                VALUES ('nimbus-mobility', 'Nimbus Mobility', 'EV / Energy', 'Series A')
                ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug  -- keeps any edits; only returns the id
                RETURNING id
                """
            )
        )
        company_id = cur.fetchone()[0]
        # Sector-news keywords for the pilot company (admins can change them; never overwritten).
        cur.execute(
            q("UPDATE companies SET news_keywords = %s WHERE id = %s AND news_keywords IS NULL"),
            (PILOT_NEWS_KEYWORDS, company_id),
        )
        seed_starter_sources(cur)

        # Demo accounts (local only, password demo1234). The analyst account is Nimbus Mobility's
        # assigned portfolio analyst, so it shows the "assigned companies only" scoping.
        upsert_user(cur, "riya@nimbus.demo", pw, "Riya Sharma", "founder", company_id, ["founder"])
        upsert_user(cur, "analyst@team.demo", pw, "Sara Thomas", "staff", None, ["analyst"])
        # Demo Admin (tier 2): Nimbus Mobility's relationship manager, so it sees that company only.
        upsert_user(cur, "manager@team.demo", pw, "Dev Malhotra", "staff", None, ["admin"])
        seed_super_admin(cur, pw)

        # Pre-alpha placeholder rows had no slug and no file. Remove them, keeping any a founder
        # request still points at (archived, so founders never see a resource without a file).
        cur.execute(
            q(
                """
                DELETE FROM resources r WHERE r.slug IS NULL
                AND NOT EXISTS (SELECT 1 FROM founder_help h WHERE h.resource_id = r.id)
                """
            )
        )
        cur.execute(q("UPDATE resources SET status = 'archived' WHERE slug IS NULL"))

        # Upsert the alpha catalog by slug so re-seeding never breaks request/download history.
        for item in CATALOG:
            approved = item["status"] == "approved"
            cur.execute(
                q(
                    """
                    INSERT INTO resources (slug, company_id, category, subcategory, title, description, resource_type,
                        review_note, is_portfolio_wide, status, file_name, content_owner, tags, submitted_by,
                        reviewed_by, reviewed_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Portal team (alpha seed)',
                        %s, %s, NOW())
                    ON CONFLICT (slug) DO UPDATE SET
                        company_id = EXCLUDED.company_id, category = EXCLUDED.category,
                        subcategory = EXCLUDED.subcategory, title = EXCLUDED.title,
                        description = EXCLUDED.description, resource_type = EXCLUDED.resource_type,
                        review_note = EXCLUDED.review_note, is_portfolio_wide = EXCLUDED.is_portfolio_wide,
                        file_name = EXCLUDED.file_name, content_owner = EXCLUDED.content_owner,
                        tags = EXCLUDED.tags, updated_at = NOW()
                    """
                ),
                (
                    item["slug"],
                    company_id if item["company_specific"] else None,
                    item["category"],
                    item["sub"],
                    item["title"],
                    item["desc"],
                    item["type"],
                    ALPHA_REVIEW_NOTE if approved else "Awaiting Monday content review",
                    not item["company_specific"],
                    item["status"],
                    item["file_name"],
                    item["owner"],
                    item["tags"],
                    "Portal team (alpha seed)" if approved else None,
                    datetime.now(timezone.utc) if approved else None,
                ),
            )
        # Note: ON CONFLICT deliberately leaves status/reviewer untouched, so approvals or
        # rejections made in the analyst workspace survive a re-seed.

        # Alpha: no automatic news. Withdraw feed-matched headlines published before that, since they
        # carry publishers' excerpts; hand-written updates are kept.
        cur.execute(q("UPDATE sector_updates SET expires_at = NOW() WHERE news_item_id IS NOT NULL AND expires_at > NOW()"))
        # Replace only the seeded sample briefs; updates published by an admin are kept.
        cur.execute(
            q("DELETE FROM sector_updates WHERE company_id = %s AND source LIKE %s AND published_by IS NULL"),
            (company_id, "%(sample brief)"),
        )
        cur.execute(
            q("SELECT 1 FROM sector_updates WHERE company_id = %s AND news_item_id IS NOT NULL AND expires_at > NOW() LIMIT 1"), (company_id,)
        )
        has_live_news = cur.fetchone() is not None
        # Sample briefs for the pilot company, labelled as samples until the research desk publishes real ones.
        for label, title, summary, source, age_days in [
            ("POLICY", "Battery policy compliance checklist updated",
             "Review the refreshed operating checklist and confirm ownership of the applicable actions.",
             "Demo Ventures research desk (sample brief)", 0),
            ("MARKET", "EV financing activity: Q3 founder brief",
             "A short view of financing patterns, investor themes and signals relevant to growth-stage mobility businesses.",
             "Approved public sources (sample brief)", 1),
            ("REGULATORY", "Connected-vehicle data readiness: action note",
             "Product and compliance teams can use this brief to review data-governance responsibilities and next steps.",
             "Demo Ventures legal network (sample brief)", 5),
        ] if not has_live_news and samples_wanted() else []:  # once real feed news is published, samples are not re-added
            cur.execute(
                q(
                    """
                    INSERT INTO sector_updates (company_id, label, title, summary, sector, source, published_at, expires_at)
                    VALUES (%s, %s, %s, %s, 'EV / Energy', %s, NOW() - make_interval(days => %s),
                            NOW() + make_interval(days => 30 - %s))
                    """
                ),
                (company_id, label, title, summary, source, age_days, age_days),
            )

        # Connect directory: the fictional demo list in backend/data/demo_connects.json.
        apply_connects(cur, load_connects(), keep_staff_added=True)

        # Sample events (from the approved wireframe), dated relative to today and labelled as samples.
        ist = timezone(timedelta(hours=5, minutes=30))
        today_ist = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
        for title, desc, location, days, hour, minutes, company_only, recording in (SAMPLE_EVENTS if samples_wanted() else []):
            start = today_ist + timedelta(days=days, hours=hour)
            cur.execute(
                q(
                    """
                    INSERT INTO events (title, description, location, starts_at, ends_at, company_id, recording_url, is_sample)
                    SELECT %s, %s, %s, %s, %s, %s, %s, TRUE
                    WHERE NOT EXISTS (SELECT 1 FROM events WHERE title = %s AND created_by IS NULL)
                    """
                ),
                (title, desc, location, start, start + timedelta(minutes=minutes), company_id if company_only else None, recording, title),
            )

        # Initial Demo Ventures team for the pilot company (from the approved wireframe). Later changes are
        # made in the admin workspace and kept as history, so only seed when nothing is assigned yet.
        for role, person in (("relationship_partner", "Dev Malhotra"), ("portfolio_analyst", "Sara Thomas")):
            cur.execute(
                q(
                    """
                    INSERT INTO company_assignments (company_id, role, person, assigned_by)
                    SELECT %s, %s, %s, 'Portal team (alpha seed)'
                    WHERE NOT EXISTS (SELECT 1 FROM company_assignments WHERE company_id = %s AND role = %s)
                    """
                ),
                (company_id, role, person, company_id, role),
            )
        seed_portfolio(cur, pw, upsert_user, samples=samples_wanted())  # five more portfolio companies and their Demo Ventures team
        # Playbook owners are Demo Ventures accounts (an owner with no account was shown to founders before 23 Oct).
        link_assignments_to_staff(cur)

        # Pilot playbook: starter tasks once (Foundation done, first Operations task done), then
        # progress is always calculated from tasks. Owner is set once; admins change it later.
        cur.execute(
            q(
                """
                INSERT INTO playbook_progress (company_id, playbook_name, progress_pct, current_phase, owner_name)
                SELECT %s, '100-Day Founder Playbook', 0, 'Foundation · Days 1–30', 'Dev Malhotra'
                WHERE NOT EXISTS (SELECT 1 FROM playbook_progress WHERE company_id = %s)
                """
            ),
            (company_id, company_id),
        )
        if seed_template_tasks(cur, company_id):
            cur.execute(
                q(
                    """
                    UPDATE playbook_tasks SET done = TRUE, done_at = NOW() - INTERVAL '20 days', done_by = 'Riya Sharma'
                    WHERE company_id = %s AND (phase_no = 1 OR (phase_no = 2 AND sort_order = (
                        SELECT MIN(sort_order) FROM playbook_tasks WHERE company_id = %s AND phase_no = 2)))
                    """
                ),
                (company_id, company_id),
            )
        if samples_wanted():
            seed_hiring_sample(cur, company_id)
        cur.execute(q("SELECT id FROM companies"))
        for (cid,) in cur.fetchall():
            seed_template_tasks(cur, cid)
            sync_progress(cur, cid)
        conn.commit()

    print("Schema + seed OK (postgres).")
    print("  Founder: riya@nimbus.demo / demo1234")
    print("  Super Admin:   superadmin@team.demo / demo1234 (unless the role has been handed over)")
    print("  Admin:         manager@team.demo / demo1234 (Dev Malhotra, relationship manager for Nimbus Mobility)")
    print("  Analyst:       analyst@team.demo / demo1234 (Sara Thomas, assigned to Nimbus Mobility)")
    print("  Second Admin:  admin2@team.demo (Tara Menon); analysts analyst2-4@team.demo; founders of Ledgerly Fintech, Kirana Cloud,")
    print("                 Orbit Health, Greenrow Agritech and Ringly at <name>@<company>.demo (all demo1234)")


def main() -> None:
    apply_schema()
    if "--schema-only" in sys.argv[1:]:
        print("Schema OK (no demo data loaded).")
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            real = holds_real_data(cur)
    if real:
        print("Schema OK. This database holds real data, so no demo data was loaded.")
        return
    seed()


if __name__ == "__main__":
    main()
