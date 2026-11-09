"""Provision an alpha portfolio company and invite its founder(s).

The company is the provisioning root (a product rule); several users may belong to one company.
Prints a one-time temporary password per user, share it through a private channel and ask the
founder to change it after first sign-in (profile menu → Change password).

    python backend/scripts/provision_company.py --company "Acme Robotics" --slug acme-robotics \
        --sector "Robotics" --stage "Seed" --user "Anika Sen:anika@acme.example"

Re-running for an existing slug adds or re-invites users; existing passwords are only reset with --reset.
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

import bcrypt
from email_validator import EmailNotValidError, validate_email

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.db import get_conn  # noqa: E402
from backend.playbook import seed_template_tasks, sync_progress  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", required=True)
    ap.add_argument("--slug", required=True, help="lowercase-with-dashes, stable identifier")
    ap.add_argument("--sector", default=None)
    ap.add_argument("--stage", default=None)
    ap.add_argument("--user", action="append", required=True, help='"Full Name:email", repeat for several users')
    ap.add_argument("--reset", action="store_true", help="issue a new temporary password for existing users")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", args.slug):
        raise SystemExit("--slug must be lowercase letters, digits and dashes")
    users = []
    for spec in args.user:
        name, _, email = spec.rpartition(":")
        if not name or "@" not in email:
            raise SystemExit(f'--user must look like "Full Name:email", got {spec!r}')
        try:  # same rules the login endpoint applies, so every invited user can actually sign in
            email = validate_email(email.strip(), check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise SystemExit(f"{email}: {exc}")
        users.append((name.strip(), email.lower()))

    issued = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (slug, name, sector, stage) VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name,
                    sector = COALESCE(EXCLUDED.sector, companies.sector), stage = COALESCE(EXCLUDED.stage, companies.stage)
                RETURNING id
                """,
                (args.slug, args.company, args.sector, args.stage),
            )
            company_id = cur.fetchone()[0]
            for name, email in users:
                cur.execute("SELECT id, account_type, company_id FROM users WHERE email = %s", (email,))
                existing = cur.fetchone()
                if existing and (existing[1] != "founder" or existing[2] not in (None, company_id)):
                    raise SystemExit(f"{email} already exists as {existing[1]} / another company, not changed")
                if existing and not args.reset:
                    cur.execute("UPDATE users SET company_id = %s, active = TRUE WHERE id = %s", (company_id, existing[0]))
                    issued.append((name, email, "(unchanged, pass --reset to issue a new one)"))
                    continue
                temp = secrets.token_urlsafe(9)
                pw_hash = bcrypt.hashpw(temp.encode(), bcrypt.gensalt()).decode()
                cur.execute(
                    """
                    INSERT INTO users (email, password_hash, full_name, account_type, company_id)
                    VALUES (%s, %s, %s, 'founder', %s)
                    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash,
                        full_name = EXCLUDED.full_name, company_id = EXCLUDED.company_id, active = TRUE
                    RETURNING id
                    """,
                    (email, pw_hash, name, company_id),
                )
                uid = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'founder', 'provision_company.py') "
                    "ON CONFLICT DO NOTHING",
                    (uid,),
                )
                issued.append((name, email, temp))
            seed_template_tasks(cur, company_id)
            sync_progress(cur, company_id)
        conn.commit()

    print(f"Company: {args.company} ({args.slug}) · id {company_id}")
    for name, email, temp in issued:
        print(f"  {name} <{email}>  temporary password: {temp}")
    print("Share each password privately; founders change it from the profile menu after signing in.")


if __name__ == "__main__":
    main()
