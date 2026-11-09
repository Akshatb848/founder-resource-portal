"""Whether a database holds real portfolio data or demo/test data.

A database is "real" once someone runs `python -m backend.scripts.mark_real_data --confirm` against it.
Demo seeding, the demo reset and the smoke test refuse to touch a real database, so real records are
never deleted or overwritten by tooling. Everything else (the API, schema updates) works the same.
"""
from __future__ import annotations

import psycopg

REAL = "real"
DEMO = "demo"
TEST_DB = "founder_portal_test"  # the throw-away database releases and tests run against


def data_mode(cur) -> str:
    """'real' or 'demo'. A database without the settings table (older schema) counts as demo."""
    try:
        cur.execute("SELECT value FROM portal_settings WHERE key = 'data_mode'")
    except psycopg.errors.UndefinedTable:
        cur.connection.rollback()
        return DEMO
    row = cur.fetchone()
    return REAL if row and row[0] == REAL else DEMO


def holds_real_data(cur) -> bool:
    return data_mode(cur) == REAL


def refuse_if_real(cur, what: str) -> None:
    """Stop a script before it changes a database that holds real data."""
    if holds_real_data(cur):
        raise SystemExit(
            f"Refusing to {what}: this database holds real portfolio data (portal_settings.data_mode = real).\n"
            "Demo data and tests run on the separate test database (a database whose name ends in _test). "
            "To go back to an earlier state, restore a database backup."
        )
