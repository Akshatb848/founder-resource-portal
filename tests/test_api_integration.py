"""API integration tests against a real, freshly seeded Postgres database.

Run with FP_TEST_DB=1 and PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD set to a throw-away
database (CI starts one as a service). The database is seeded with `python -m backend.seed`.
"""
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from .conftest import ROOT

pytestmark = pytest.mark.skipif(os.getenv("FP_TEST_DB") != "1", reason="set FP_TEST_DB=1 with a test Postgres")

PASSWORD = "demo1234"  # demo password created by backend/seed.py


@pytest.fixture(scope="module")
def client():
    from backend.data_mode import holds_real_data
    from backend.db import get_conn

    with get_conn() as conn, conn.cursor() as cur:
        if holds_real_data(cur):  # these tests sign in with demo passwords and change records
            pytest.exit("Refusing to run the database tests against a database that holds real data", returncode=2)
    subprocess.run([sys.executable, "-m", "backend.seed"], cwd=ROOT, check=True)  # noqa: S603
    from backend.main import app

    with TestClient(app) as c:  # runs the lifespan: DB pool + permission sync
        yield c


def login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


def test_health_ok_with_database(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] != "unreachable"


def test_wrong_password_is_rejected(client):
    r = client.post("/api/auth/login", json={"email": "riya@nimbus.demo", "password": "wrong"})
    assert r.status_code == 401


def test_founder_sees_own_company_dashboard_and_resources(client):
    headers, data = login(client, "riya@nimbus.demo")
    assert data["redirect"] == "/"
    dash = client.get("/api/founder/dashboard", headers=headers)
    assert dash.status_code == 200
    assert dash.json()["company_name"] == "Nimbus Mobility"
    resources = client.get("/api/founder/resources", headers=headers)
    assert resources.status_code == 200 and len(resources.json()) > 0


def test_role_based_access_control(client):
    founder, _ = login(client, "riya@nimbus.demo")
    analyst, data = login(client, "analyst@team.demo")
    assert data["redirect"] == "/analyst.html"
    assert client.get("/api/analyst/work-items", headers=founder).status_code == 403
    assert client.get("/api/analyst/work-items", headers=analyst).status_code == 200
    assert client.post("/api/founder/help", headers=analyst, json={"subject": "x", "context": "x"}).status_code == 403


def test_sign_out_revokes_the_session(client):
    headers, _ = login(client, "riya@nimbus.demo")
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_three_tiers_sign_in_to_the_workspace(client):
    for email, role in (("superadmin@team.demo", "super_admin"), ("manager@team.demo", "admin"), ("analyst@team.demo", "analyst")):
        _, data = login(client, email)
        assert data["redirect"] == "/analyst.html"
        assert data["user"]["roles"] == [role]


def test_only_the_super_admin_sees_approvals(client):
    admin, _ = login(client, "superadmin@team.demo")
    manager, _ = login(client, "manager@team.demo")
    assert client.get("/api/admin/approvals", headers=admin).status_code == 200
    assert client.get("/api/admin/approvals", headers=manager).status_code == 403


def test_news_suggestions_are_off_in_alpha(client):
    admin, _ = login(client, "superadmin@team.demo")
    assert client.get("/api/admin/news/sources", headers=admin).status_code == 404


def test_one_time_code_sign_in_when_switched_on(client, monkeypatch):
    """OTP sign-in (off by default): a code works once, wrong codes fail, the outbox hides the code from staff."""
    import re

    from backend import config
    from backend.db import get_conn

    monkeypatch.setattr(config, "OTP_SIGNIN_ENABLED", True)
    assert client.get("/api/auth/options").json()["otp"] is True
    email = "riya@nimbus.demo"
    r1 = client.post("/api/auth/otp/request", json={"email": email})
    r2 = client.post("/api/auth/otp/request", json={"email": "nobody@nowhere.example.org"})
    assert r1.status_code == 200 and r2.status_code == 200 and r1.json() == r2.json()  # never reveals an account
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT body FROM email_outbox WHERE to_email = %s AND kind = 'otp' ORDER BY id DESC LIMIT 1", (email,))
        code = re.search(r"\b(\d{6})\b", cur.fetchone()[0]).group(1)
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/api/auth/otp/verify", json={"email": email, "code": wrong}).status_code == 401
    ok = client.post("/api/auth/otp/verify", json={"email": email, "code": code})
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["email"] == email and ok.json()["redirect"] == "/"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['token']}"})
    assert me.status_code == 200
    assert client.post("/api/auth/otp/verify", json={"email": email, "code": code}).status_code == 401  # works once
    admin, _ = login(client, "superadmin@team.demo")
    out = client.get("/api/admin/outbox", headers=admin).json()
    mine = [m for m in out if m["kind"] == "otp" and m["to_email"] == email]
    assert mine and all(code not in m["body"] and code not in m["subject"] for m in mine)
