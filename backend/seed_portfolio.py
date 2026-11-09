"""Demo portfolio: five more fictional portfolio companies and the fictional fund team that runs them.

Every company, founder and staff member here is invented for the public demo ("Fictional demo company").
Founder and staff accounts use non-routable `.demo` addresses. Demo password for every account: demo1234.

Team structure (mapped to the one Super Admin, superadmin@team.demo, Neha Verma):
    Super Admin  Neha Verma     superadmin@team.demo
      Admin  Dev Malhotra   manager@team.demo  -> Nimbus Mobility, Ledgerly Fintech, Kirana Cloud
        Analyst  Sara Thomas   analyst@team.demo   -> Nimbus Mobility, Ledgerly Fintech
        Analyst  Arjun Nair    analyst2@team.demo  -> Kirana Cloud
      Admin  Tara Menon     admin2@team.demo   -> Orbit Health, Greenrow Agritech, Ringly
        Analyst  Zoya Khan     analyst3@team.demo  -> Orbit Health, Greenrow Agritech
        Analyst  Vikram Joshi  analyst4@team.demo  -> Ringly
"""
from __future__ import annotations

from backend.sqlutil import q
from backend.playbook import seed_template_tasks, sync_progress

# slug: (name, sector, city, funds, invested, short description, founders [(name, email)], admin, analyst, tasks done)
PORTFOLIO = {
    "nimbus-mobility": ("Nimbus Mobility", "EV / Mobility", "Bengaluru", "Fund II", "May 2021",
                        "Fictional demo company: battery-swapping network for electric three-wheelers and last-mile fleets.",
                        [], "Dev Malhotra", "Sara Thomas", None),
    "ledgerly": ("Ledgerly Fintech", "FinTech", "Mumbai", "Fund III", "June 2024",
                 "Fictional demo company: accounts-payable automation and supplier credit for mid-sized manufacturers.",
                 [("Kabir Mehta", "kabir@ledgerly.demo")], "Dev Malhotra", "Sara Thomas", 3),
    "kirana-cloud": ("Kirana Cloud", "Retail SaaS", "Gurugram", "Fund III", "April 2022",
                     "Fictional demo company: inventory, billing and reordering app for neighbourhood grocery stores.",
                     [("Ishaan Gupta", "ishaan@kiranacloud.demo")], "Dev Malhotra", "Arjun Nair", 1),
    "orbit-health": ("Orbit Health", "HealthTech / AI", "Pune", "Fund II", "July 2020",
                     "Fictional demo company: remote patient monitoring and early-warning alerts for hospital wards.",
                     [("Meher Kapoor", "meher@orbithealth.demo"), ("Aditya Rao", "aditya@orbithealth.demo")], "Tara Menon", "Zoya Khan", 5),
    "greenrow": ("Greenrow Agritech", "AgriTech / AI", "Jaipur", "Fund III", "January 2025",
                 "Fictional demo company: satellite and weather-based crop advisories for farmer producer organisations.",
                 [("Nikhil Bose", "nikhil@greenrow.demo")], "Tara Menon", "Zoya Khan", 0),
    "ringly": ("Ringly", "SaaS / Telecom", "Hyderabad", "Fund III", "November 2024",
               "Fictional demo company: cloud business phone numbers and call tracking for small businesses.",
               [("Pooja Iyer", "pooja@ringly.demo")], "Tara Menon", "Vikram Joshi", 2),
}

# email: (name, tier, reports to (email) or None)
TEAM = {
    "admin2@team.demo": ("Tara Menon", "admin", None),
    "analyst2@team.demo": ("Arjun Nair", "analyst", "manager@team.demo"),
    "analyst3@team.demo": ("Zoya Khan", "analyst", "admin2@team.demo"),
    "analyst4@team.demo": ("Vikram Joshi", "analyst", "admin2@team.demo"),
    "analyst@team.demo": ("Sara Thomas", "analyst", "manager@team.demo"),
}

# One clearly labelled sample brief per new company, so each dashboard shows the feature until real updates are written.
SAMPLE_BRIEFS = {
    "ledgerly": ("REGULATORY", "Digital lending disclosures: watch list", "What proposed disclosure rules could mean for embedded supplier credit."),
    "kirana-cloud": ("MARKET", "Small-store digitisation: market note", "How neighbourhood stores choose billing tools, and what makes them switch."),
    "orbit-health": ("REGULATORY", "Medical device registration: checklist", "Steps to keep remote-monitoring devices compliant as hospital deployments grow."),
    "greenrow": ("MARKET", "Agri-data buyers: where demand is growing", "Enterprises, insurers and governments buying crop intelligence, and what they ask for."),
    "ringly": ("MARKET", "SMB communication tools: market note", "How small businesses choose calling and messaging tools, and the switching triggers."),
}


def seed_portfolio(cur, pw_hash: str, upsert_user, samples: bool = True) -> None:
    for email, (name, tier, _) in TEAM.items():
        upsert_user(cur, email, pw_hash, name, "staff", None, [tier])
    for email, (_, _, boss) in TEAM.items():
        cur.execute(
            q("UPDATE users SET reports_to = (SELECT id FROM users WHERE email = %s) WHERE email = %s"),
            (boss, email),
        )

    for slug, (name, sector, city, funds, invested, about, founders, admin, analyst, done) in PORTFOLIO.items():
        cur.execute(
            q(
                """
                INSERT INTO companies (slug, name, sector, city, fund, invested, about)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug  -- keeps edits made in the workspace
                RETURNING id
                """
            ),
            (slug, name, sector, city, funds, invested, about),
        )
        cid = cur.fetchone()[0]
        for full_name, email in founders:
            upsert_user(cur, email, pw_hash, full_name, "founder", cid, ["founder"])
        for role, person in (("relationship_partner", admin), ("portfolio_analyst", analyst)):
            cur.execute(
                q(
                    """
                    INSERT INTO company_assignments (company_id, role, person, assigned_by)
                    SELECT %s, %s, %s, 'Portal team (alpha seed)'
                    WHERE NOT EXISTS (SELECT 1 FROM company_assignments WHERE company_id = %s AND role = %s)
                    """
                ),
                (cid, role, person, cid, role),
            )
        if done is None:
            continue  # Nimbus Mobility's playbook and briefs are seeded by seed.py
        cur.execute(
            q(
                """
                INSERT INTO playbook_progress (company_id, playbook_name, progress_pct, current_phase, owner_name)
                SELECT %s, '100-Day Founder Playbook', 0, 'Foundation · Days 1–30', %s
                WHERE NOT EXISTS (SELECT 1 FROM playbook_progress WHERE company_id = %s)
                """
            ),
            (cid, admin, cid),
        )
        if seed_template_tasks(cur, cid) and done and founders:
            cur.execute(
                q(
                    """
                    UPDATE playbook_tasks SET done = TRUE, done_at = NOW() - INTERVAL '6 days', done_by = %s
                    WHERE id IN (SELECT id FROM playbook_tasks WHERE company_id = %s ORDER BY phase_no, sort_order, id LIMIT %s)
                    """
                ),
                (founders[0][0], cid, done),
            )
        sync_progress(cur, cid)
        label, title, summary = SAMPLE_BRIEFS[slug]
        if not samples:
            continue
        cur.execute(
            q(
                """
                INSERT INTO sector_updates (company_id, label, title, summary, sector, source, published_at, expires_at)
                SELECT %s, %s, %s, %s, %s, 'Demo Ventures research desk (sample brief)', NOW() - INTERVAL '2 days', NOW() + INTERVAL '28 days'
                WHERE NOT EXISTS (SELECT 1 FROM sector_updates WHERE company_id = %s AND title = %s)
                """
            ),
            (cid, label, title, summary, sector, cid, title),
        )
