"""Database access.

The API keeps a small pool of open connections (opening a new Postgres connection costs ~100 ms, which
made every request slow). Scripts and other databases still connect directly.

    with get_conn() as conn:          # commits on success, rolls back on an exception
        with conn.cursor() as cur: ...
"""
from __future__ import annotations

import os
import threading
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from backend.config import POSTGRES_CONFIG

POOL_MIN = int(os.getenv("PG_POOL_MIN", "2"))
# Database connections the API keeps open at most (PostgreSQL allows 100 in all).
POOL_MAX = int(os.getenv("PG_POOL_MAX", "20"))
# How long a request waits for a free connection when the portal is very busy. After that it gets a quick
# "busy, try again" reply (HTTP 503, handled in main.py) instead of hanging.
POOL_WAIT_SECONDS = float(os.getenv("PG_POOL_WAIT_SECONDS", "5"))
# A pool with room to grow hands out a connection within milliseconds; if none comes within this time, the
# pool is reconnecting after a database restart and a direct connection is used instead (see get_conn).
QUICK_WAIT_SECONDS = 0.5

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _dsn(dbname: str | None = None) -> str:
    c = POSTGRES_CONFIG
    name = dbname or c["dbname"]
    if not (c.get("password") or "").strip():
        raise RuntimeError(
            "PG_PASSWORD is missing. Copy backend/.env.example to backend/.env (local Postgres only)."
        )
    dsn = (
        f"host={c['host']} port={c['port']} dbname={name} "
        f"user={c['user']} password={c['password']}"
    )
    # The central PostgreSQL server needs encrypted connections (PG_SSLMODE, PG_SSLROOTCERT in backend/.env).
    if c.get("sslmode"):
        dsn += f" sslmode={c['sslmode']}"
    if c.get("sslrootcert"):
        dsn += f" sslrootcert={c['sslrootcert']}"
    return dsn


def open_pool() -> None:
    """Start the shared pool (called when the API starts). Connections are checked before use, so a
    database restart does not break requests."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                _dsn(),
                min_size=POOL_MIN,
                max_size=POOL_MAX,
                kwargs={"connect_timeout": 15},
                check=ConnectionPool.check_connection,
                open=False,
                name="founder-portal",
            )
            _pool.open(wait=False)


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def _direct_conn() -> Iterator[Any]:
    try:
        conn = psycopg.connect(_dsn(), connect_timeout=5)
    except psycopg.OperationalError as exc:  # database down: the API answers "busy, try again" (503)
        raise PoolTimeout("database unavailable") from exc
    with conn:
        yield conn


@contextmanager
def get_conn(dbname: str | None = None) -> Iterator[Any]:
    if _pool is not None and dbname is None:
        stack = ExitStack()
        first_wait = min(QUICK_WAIT_SECONDS, POOL_WAIT_SECONDS)
        try:
            conn = stack.enter_context(_pool.connection(timeout=first_wait))
        except PoolTimeout:
            if _pool.get_stats().get("pool_size", 0) >= _pool.max_size:
                # Every connection is in use: really busy. Wait the rest of PG_POOL_WAIT_SECONDS for one to come
                # back; after that the caller gets the quick "busy" reply (503).
                conn = stack.enter_context(_pool.connection(timeout=max(0.1, POOL_WAIT_SECONDS - first_wait)))
            else:
                # The pool has room but no connection: the database restarted and the pool is still
                # reconnecting (it backs off between attempts). Use a direct connection meanwhile, so the portal
                # works again as soon as the database does.
                conn = stack.enter_context(_direct_conn())
        with stack:
            yield conn
        return
    with psycopg.connect(_dsn(dbname), connect_timeout=15) as conn:
        yield conn


def db_label() -> str:
    return "postgres"
