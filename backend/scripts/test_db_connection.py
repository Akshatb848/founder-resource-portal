"""Check the database connection in backend/.env, without changing anything.

    python backend/scripts/test_db_connection.py

Prints the server, database, PostgreSQL version, whether the connection is encrypted (SSL), whether the
login may create tables (needed for schema updates) and the data mode. Passwords are never printed.
Useful when pointing the portal at the central PostgreSQL server (dev or production).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg  # noqa: E402

from backend.config import POSTGRES_CONFIG  # noqa: E402
from backend.db import _dsn  # noqa: E402


def main() -> None:
    cfg = POSTGRES_CONFIG
    if not cfg.get("password"):
        print("Set PG_PASSWORD in backend/.env first.")
        sys.exit(1)
    try:
        with psycopg.connect(_dsn(), connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW server_version")
                version = cur.fetchone()[0]
                cur.execute("SELECT COALESCE((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false)")
                ssl = cur.fetchone()[0]
                cur.execute("SELECT has_database_privilege(current_user, current_database(), 'CREATE'), "
                            "has_schema_privilege(current_user, 'public', 'CREATE')")
                can_db, can_schema = cur.fetchone()
                cur.execute("SELECT to_regclass('public.portal_settings') IS NOT NULL")
                has_settings = cur.fetchone()[0]
                mode = "empty database"
                if has_settings:
                    cur.execute("SELECT value FROM portal_settings WHERE key = 'data_mode'")
                    row = cur.fetchone()
                    mode = row[0] if row else "demo"
        print(f"OK: connected to {cfg['host']}:{cfg['port']}, database {cfg['dbname']}, as {cfg['user']}")
        print(f"PostgreSQL {version}; encrypted (SSL): {'yes' if ssl else 'NO'}")
        print(f"May create tables: {'yes' if can_schema else 'NO (schema updates will fail)'}; data: {mode}")
        if not ssl and cfg["host"] not in ("localhost", "127.0.0.1"):
            print("Warning: the connection to a remote server is not encrypted. Set PG_SSLMODE=require.")
    except Exception as e:  # noqa: BLE001
        print("Connection failed:", e)
        print("Check PG_HOST, PG_PORT, PG_SSLMODE, the server's firewall (it must allow this machine), and that",
              "database", cfg["dbname"], "exists.")
        sys.exit(1)


if __name__ == "__main__":
    main()
