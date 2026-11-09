"""The pages people use without being signed in, end to end in a real browser (test copy only):
1. a public interest page for an opening (careers.html?r=<token>): the form submits and confirms;
2. Forgot password on the sign-in page: the request is accepted and the screen says what happens next;
3. an invitation link (#invite / set-password): the person sets a password and lands in their portal.

    python tests/e2e/check_public_pages.py --base http://127.0.0.1:8001
"""
from __future__ import annotations

import argparse
import sys

import requests
from playwright.sync_api import sync_playwright

PW = "demo1234"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    a = ap.parse_args()
    b = a.base
    if requests.get(b + "/api/health", timeout=10).json().get("data") != "demo":
        sys.exit("Refusing: run only against the test copy.")
    fails = []

    def check(ok, what):
        print(("OK   " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    founder = requests.Session()
    founder.headers["Authorization"] = "Bearer " + founder.post(b + "/api/auth/login", json={"email": "riya@nimbus.demo", "password": PW}).json()["token"]
    roles = founder.get(b + "/api/founder/hiring").json()
    role = (roles.get("roles") if isinstance(roles, dict) else roles)[0]
    link = founder.post(f"{b}/api/founder/hiring/roles/{role['id']}/link", json={"on": True}).json()
    url = link.get("interest_link")
    check(bool(url and "careers.html?r=" in url), f"founder creates a public interest link for '{role['title']}'")
    url = b + url[url.index("/careers.html"):]

    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1366, "height": 800})
        p = ctx.new_page()
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)[:200]))
        p.on("console", lambda m: m.type == "error" and errs.append(m.text[:200]))

        # 1. Public interest page
        p.goto(url, wait_until="networkidle")
        check(role["title"].split(" (")[0] in p.inner_text("body"), "the interest page shows the opening")
        form = p.locator("form").first
        for inp in form.locator("input:visible, textarea:visible").all():
            t = (inp.get_attribute("type") or "text").lower()
            if t in ("checkbox",):
                inp.check()
                continue
            if t == "file":
                continue
            val = {"email": "candidate.e2e@example.com", "tel": "9876543210", "url": "https://example.com/e2e",
                   "number": "5"}.get(t, "End-to-end candidate test")
            inp.fill(val)
        form.locator("button[type=submit]").click()
        p.wait_for_timeout(1500)
        body = p.inner_text("body")
        check(any(w in body.lower() for w in ("thank", "received", "sent", "we will", "we'll")), "the interest form submits and confirms")

        # 2. Forgot password
        p.goto(b + "/", wait_until="networkidle")
        p.locator("[data-forgot]").click()
        p.locator("#forgotEmail").fill("riya@nimbus.demo")
        p.locator("[data-send-reset]").click()
        p.wait_for_timeout(1200)
        msg = p.locator("[data-forgot-msg]").inner_text()
        check(bool(msg.strip()) and "error" not in msg.lower(), f"Forgot password confirms: {msg[:90]!r}")

        # 3. Invitation link: an analyst invites a new founder; the founder sets a password and lands in the portal
        staff = requests.Session()
        staff.headers["Authorization"] = "Bearer " + staff.post(b + "/api/auth/login", json={"email": "superadmin@team.demo", "password": PW}).json()["token"]
        cos = staff.get(b + "/api/admin/companies").json()
        cid = (cos.get("companies") if isinstance(cos, dict) else cos)[0]["id"]
        inv = staff.post(f"{b}/api/admin/companies/{cid}/founders", json={"full_name": "E2E Founder", "email": "e2e.founder@example.com", "send_email": False}).json()
        invite = inv.get("invite_link") or inv.get("link") or inv.get("url")
        check(bool(invite), "the Super Admin gets an invitation link for a new founder")
        if invite:
            p.goto(b + invite[invite.index("/", 8):] if invite.startswith("http") else b + invite, wait_until="networkidle")
            pws = p.locator("input[type=password]")
            check(pws.count() >= 1, "the invitation link opens the set-password page")
            for i in range(pws.count()):
                pws.nth(i).fill("E2e-Strong-Pass-2026")
            p.locator("button[type=submit]").first.click()
            p.wait_for_timeout(2500)
            check("E2E Founder" in p.inner_text("body") or "Good" in p.inner_text("body"), "after setting a password the founder lands in their portal")
        check(not errs, f"no browser errors on public pages {errs[:3]}")
        br.close()
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
