"""Make one person the Super Admin from the server console (there is exactly one).

    python -m backend.scripts.create_super_admin --email name@team.demo --name "Full Name"

Use it on a new server, or if the Super Admin has left and nobody can sign in to hand the role over.
Normally the Super Admin hands the role over in Workspace -> Team & access. The previous Super Admin
becomes an Analyst. A new account gets a one-time password; share it privately.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

import bcrypt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db import get_conn  # noqa: E402
from backend.permissions import sync_access_model  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    email = args.email.strip().lower()
    temp = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            sync_access_model(cur)
            cur.execute("SELECT id, account_type FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row and row[1] != "staff":
                raise SystemExit(f"{email} is a founder account; founders cannot be Super Admin.")
            if row:
                uid = row[0]
                cur.execute("UPDATE users SET active = TRUE WHERE id = %s", (uid,))
            else:
                temp = secrets.token_urlsafe(12)
                pw_hash = bcrypt.hashpw(temp.encode(), bcrypt.gensalt()).decode()
                cur.execute(
                    "INSERT INTO users (email, password_hash, full_name, account_type) VALUES (%s, %s, %s, 'staff') RETURNING id",
                    (email, pw_hash, args.name.strip()),
                )
                uid = cur.fetchone()[0]
            cur.execute(
                "SELECT u.id, u.email FROM user_roles r JOIN users u ON u.id = r.user_id WHERE r.role_code = 'super_admin'"
            )
            previous = cur.fetchone()
            if previous and previous[0] != uid:
                cur.execute("DELETE FROM user_roles WHERE user_id = %s AND role_code = 'super_admin'", (previous[0],))
                cur.execute(
                    "INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'analyst', 'server console') ON CONFLICT DO NOTHING",
                    (previous[0],),
                )
            cur.execute("DELETE FROM user_roles WHERE user_id = %s AND role_code <> 'super_admin'", (uid,))
            cur.execute(
                "INSERT INTO user_roles (user_id, role_code, granted_by) VALUES (%s, 'super_admin', 'server console') ON CONFLICT DO NOTHING",
                (uid,),
            )
            cur.execute(
                "INSERT INTO admin_audit (actor, action, target, details) VALUES ('server console', 'super_admin.handover', %s, %s)",
                (email, json.dumps({"from": previous[1] if previous else None, "to": email})),
            )
        conn.commit()
    print(f"{email} is now the Super Admin.")
    if temp:
        print(f"One-time password: {temp}  (share privately; change it after the first sign-in)")


if __name__ == "__main__":
    main()
