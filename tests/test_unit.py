"""Database-free unit tests for access control, news matching and the HTTP boundary."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import permissions
from backend.news_feed import FeedError, score_item, suggest_label, validate_feed_url
from backend.security import has_perm

ROOT = Path(__file__).resolve().parents[1]


def test_every_role_grants_only_known_permissions():
    for code, (_name, _staff, _tier, grants) in permissions.ROLES.items():
        unknown = set(grants) - set(permissions.PERMISSIONS)
        assert not unknown, f"{code} grants unknown permissions {unknown}"
        assert set(grants.values()) <= {permissions.ALL, permissions.ASSIGNED}


def test_three_staff_tiers_in_order():
    staff = sorted((tier, code) for code, (_n, is_staff, tier, _g) in permissions.ROLES.items() if is_staff)
    assert [code for _t, code in staff] == ["super_admin", "admin", "analyst"]


def test_founder_role_is_limited_to_the_portal():
    _name, is_staff, _tier, grants = permissions.ROLES["founder"]
    assert not is_staff
    assert set(grants) == {"portal.use"}


def test_only_the_super_admin_approves_and_admins_set_up_only_their_own_companies():
    # Meeting 23 Oct 2026: Admins and Analysts set companies up and invite founders, but only for their own
    # companies; approving content and managing Admins stay with the Super Admin.
    for code in ("admin", "analyst"):
        grants = permissions.ROLES[code][3]
        assert "content.approve" not in grants
        assert grants.get("companies.add") == permissions.ASSIGNED
        assert grants.get("founders.manage") == permissions.ASSIGNED
        assert "admins.manage" not in grants


def test_admins_and_analysts_are_limited_to_their_own_companies():
    for code in ("admin", "analyst"):
        grants = permissions.ROLES[code][3]
        for perm in ("companies.view", "requests.handle", "intakes.view", "founder.preview"):
            assert grants[perm] == permissions.ASSIGNED, (code, perm)


def test_admins_hold_every_analyst_access_and_the_super_admin_every_admin_access():
    """Anything an Analyst can do, their Admin and the Super Admin can do too, with at least the same reach."""
    rank = {permissions.ASSIGNED: 1, permissions.ALL: 2}
    tiers = [permissions.ROLES[c][3] for c in ("analyst", "admin", "super_admin")]
    for lower, higher in zip(tiers, tiers[1:]):
        for perm, scope in lower.items():
            assert perm in higher and rank[higher[perm]] >= rank[scope], perm


def test_every_permission_has_a_plain_language_label():
    for code, (label, desc) in permissions.PERMISSIONS.items():
        assert label and desc and "." not in label, code


def test_has_perm_matches_any_of_the_given_permissions():
    user = {"permissions": ["news.publish"]}
    assert has_perm(user, "news.publish")
    assert has_perm(user, "content.approve", "news.publish")
    assert not has_perm(user, "content.approve")
    assert not has_perm({}, "news.publish")


def test_news_scoring_prefers_title_hits_and_company_name():
    score_title, hits = score_item("RBI issues new circular", "", "Nimbus Mobility", ["RBI"])
    score_body, _ = score_item("Market wrap", "RBI mentioned in passing", "Nimbus Mobility", ["RBI"])
    score_name, _ = score_item("Nimbus Mobility expands", "", "Nimbus Mobility", [])
    assert score_title > score_body > 0
    assert hits == ["RBI"]
    assert score_name >= 6


@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("Startup raises Series A funding", "FUNDING"),
        ("New EV subsidy scheme announced", "POLICY"),
        ("Quarterly market update", "MARKET"),
    ],
)
def test_suggest_label(title, label):
    assert suggest_label("news", title, "") == label


@pytest.mark.parametrize(
    "url", ["http://example.org/feed", "https://127.0.0.1/feed", "https://localhost/feed"]
)
def test_feed_urls_must_be_public_https(url):
    with pytest.raises(FeedError):
        validate_feed_url(url)


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    # No context manager: the lifespan (DB pool, permission sync, news scheduler) is not started.
    return TestClient(app)


def test_health_reports_without_raising(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "founder-resource-portal"
    assert body["status"] in {"ok", "degraded"}


@pytest.mark.parametrize("path", ["/backend/.env", "/backend/main.py", "/.git/config", "/docs/FEATURES.md"])
def test_source_and_secrets_are_not_served(client, path):
    assert client.get(path).status_code == 404


def test_api_requires_a_session_and_sets_security_headers(client):
    r = client.get("/api/founder/resources")
    assert r.status_code == 401
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- page layout and freshness (26 Oct 2026)
# The profile block (avatar, name, Sign out) must stay visible however long the sidebar menu gets: the menu
# scrolls, the logo and the profile block never move. And every page in dist/ must load the current copy of
# each script and stylesheet (content fingerprint in ?v=), so a browser never runs a stale file.
def _css_rule(css: str, selector: str) -> str:
    import re

    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # comments are not rules
    rules = re.findall(r"(?:^|})\s*" + re.escape(selector) + r"\s*{([^}]*)}", css)
    return ";".join(rules).replace(" ", "")


def test_sidebar_keeps_the_profile_block_on_screen():
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    assert "overflow:hidden" in _css_rule(css, ".sidebar")
    nav = _css_rule(css, ".sidebar>nav")
    assert "min-height:0" in nav and "overflow-y:auto" in nav, "the sidebar menu must scroll inside the sidebar"
    assert "flex:00auto" in _css_rule(css, ".sidebar>.profile"), "the profile block must never shrink or scroll away"
    assert "flex:00auto" in _css_rule(css, ".sidebar>.brand")
    import re

    for page in ("index.html", "analyst.html"):
        html = (ROOT / page).read_text(encoding="utf-8")
        aside = re.search(r'<aside class="sidebar"[^>]*>(.*?)</aside>', html, re.S).group(1)
        assert aside.index("<nav") < aside.index('class="profile"'), f"{page}: profile block must follow the menu"
        assert re.search(r'</nav>\s*<div class="profile"', aside), f"{page}: profile block must be a direct child of the sidebar"


def test_dist_pages_load_the_current_copy_of_every_asset():
    import hashlib
    import re

    dist = ROOT / "dist"
    for page in ("index.html", "analyst.html", "careers.html"):
        html = (dist / page).read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="([A-Za-z0-9_.\-]+\.(?:js|css))(?:\?v=([^"]*))?"', html)
        assert refs, page
        for name, version in refs:
            data = (dist / name).read_bytes().replace(b"\r\n", b"\n")  # same fingerprint on Windows and Linux checkouts
            assert data == (ROOT / name).read_bytes().replace(b"\r\n", b"\n"), f"dist/{name} is out of date: run scripts/sync_dist.py"
            assert version == hashlib.sha256(data).hexdigest()[:8], f"{page} loads a stale {name}: run scripts/sync_dist.py"


def test_questionnaire_wording_matches_the_number_of_questions():
    # 26 Oct 2026: the library card still said "Seven quick questions" after the questionnaire was cut to three.
    import re

    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    wiring = (ROOT / "app-api-wiring.js").read_text(encoding="utf-8")
    block = re.search(r"const INTAKE_QUESTIONS = \[(.*?)\n\];", wiring, re.S).group(1)
    count = len(re.findall(r"^\s*\{ key:", block, re.M))
    assert count >= 1
    for name in ("app.js", "app-api-wiring.js", "app-api-alpha.js", "index.html"):
        for word in re.findall(r"\b(\w+) quick questions\b", (ROOT / name).read_text(encoding="utf-8"), re.I):
            assert words.get(word.lower()) == count, f"{name} says '{word} quick questions' but there are {count}"


def test_no_inline_event_handlers_the_security_policy_would_block():
    # 26 Oct 2026: the workspace's content-checklist Close button used onclick="…", which the portal's
    # Content-Security-Policy (script-src 'self') blocks, so the button did nothing.
    import re

    pattern = re.compile(r"""\son(click|change|submit|input|load|error|keydown|keyup|focus|blur|mouseover)\s*=\s*["']""", re.I)
    for f in sorted(ROOT.glob("*.html")) + sorted(ROOT.glob("*.js")):
        hits = [m.group(0).strip() for m in pattern.finditer(f.read_text(encoding="utf-8"))]
        assert not hits, f"{f.name} uses inline event handlers {hits[:3]}; attach them in JavaScript instead"


def test_one_time_code_sign_in_is_off_by_default(client):
    """30 Oct 2026: OTP sign-in is built but switched off; the page hides the button and the routes answer 404."""
    from backend import config

    assert config.OTP_SIGNIN_ENABLED is False
    r = client.get("/api/auth/options")
    assert r.status_code == 200 and r.json()["otp"] is False
    assert client.post("/api/auth/otp/request", json={"email": "riya@nimbus.demo"}).status_code == 404
    assert client.post("/api/auth/otp/verify", json={"email": "riya@nimbus.demo", "code": "123456"}).status_code == 404


def test_vm_error_log_keeps_warnings_in_a_rotating_file(tmp_path, monkeypatch):
    import logging
    from logging.handlers import RotatingFileHandler

    from backend import main

    log = tmp_path / "app.log"
    monkeypatch.setenv("LOG_FILE", str(log))
    main._file_logging()
    main._file_logging()  # a second start-up does not add a second handler
    lg = logging.getLogger("founder_portal")
    handlers = [h for h in lg.handlers if isinstance(h, RotatingFileHandler)]
    try:
        assert len(handlers) == 1
        lg.warning("portal busy: test entry")
        handlers[0].flush()
        assert "portal busy: test entry" in log.read_text(encoding="utf-8")
    finally:
        for name in ("founder_portal", "uvicorn.error"):
            for h in [h for h in logging.getLogger(name).handlers if isinstance(h, RotatingFileHandler)]:
                logging.getLogger(name).removeHandler(h)
                h.close()


def test_demo_connects_are_fictional_organisations_without_contact_details():
    """The public demo's Connect directory: four networks, unique names, no emails, phones or profile links."""
    import json as _json
    import re as _re
    from backend.scripts import import_connects as ic

    data = _json.loads(ic.DATA_FILE.read_text(encoding="utf-8"))["connects"]
    assert len(data) >= 20
    assert {e["network_group"] for e in data} == {"Operational Support Network", "Peer Founder Network",
                                                   "Investor & Fundraising Ecosystem", "Demo Ventures Network"}
    text = _json.dumps(data)
    assert not _re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", text), "an email address is in the list"
    assert not _re.search(r"\+?\d[\d -]{9,}\d", text), "a phone number is in the list"
    assert "linkedin.com/in/" not in text.lower()
    names = [e["display_name"] for e in data]
    assert len(names) == len(set(names))
    assert all(not e["website"] or _re.match(r"https?://", e["website"]) for e in data)
    assert all(len(e["display_name"]) <= 120 and len(e["skills"]) <= 8 for e in data)
    assert len(ic.load()) == len(data)


