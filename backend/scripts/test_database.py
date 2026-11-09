"""Create the throw-away test database (founder_portal_test) from scratch: drop it, create it, apply the
schema and load the demo data. Tests and releases run against it, never against the main database.

    python backend/scripts/test_database.py

Uses the host, port, user and password from backend/.env; only the database name differs. Local only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.data_mode import TEST_DB  # noqa: E402

os.environ["PG_DB"] = TEST_DB  # must be set before backend.config is imported

import psycopg  # noqa: E402

from backend.config import POSTGRES_CONFIG  # noqa: E402


def main() -> None:
    c = POSTGRES_CONFIG
    if c["dbname"] != TEST_DB:
        raise SystemExit("Internal error: the test database name was not applied.")
    if c["host"] not in ("127.0.0.1", "localhost"):
        raise SystemExit("Refusing: the test database is created only on the local Postgres.")
    admin = f"host={c['host']} port={c['port']} dbname=postgres user={c['user']} password={c['password']}"
    with psycopg.connect(admin, autocommit=True, connect_timeout=15) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    from backend.seed import apply_schema, seed  # imported after PG_DB points at the test database

    apply_schema()
    seed()
    import contextlib
    import io

    from backend.scripts.import_portfolio import run as import_portfolio

    with contextlib.redirect_stdout(io.StringIO()):
        import_portfolio(apply=True)  # the full Demo Ventures portfolio, as on the main database
    print(f"Test database {TEST_DB} created with schema, demo data and the full portfolio.")


if __name__ == "__main__":
    main()
