"""Browser check of the company profile's tracker fields (3 Nov 2026), on a phone and a laptop. Test copy only.

Staff open a company profile, see the staff-only Demo Ventures tracker, edit and save it; the founder's own profile shows
the new shared fields and no tracker.

    python tests/e2e/check_tracker.py --base http://127.0.0.1:8010 --shots /tmp/fp-e2e/tracker
"""
import argparse
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SIZES = {"phone": (375, 812, True), "laptop": (1366, 768, False)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    if requests.get(a.base + "/api/health", timeout=10).json().get("data") != "demo":
        sys.exit("Refusing: run only against the test copy.")
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    fails = []

    def check(ok, label):
        print(("OK   " if ok else "FAIL ") + label)
        if not ok:
            fails.append(label)

    def ctx_for(b, email, size):
        w, h, mobile = SIZES[size]
        tok = requests.post(a.base + "/api/auth/login", json={"email": email, "password": "demo1234"}).json()["token"]
        ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile)
        ctx.add_init_script(f"localStorage.setItem('frp_token','{tok}')")
        return ctx

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for size in SIZES:
            # Staff: Companies -> Nimbus Mobility -> Company profile
            ctx = ctx_for(b, "analyst@team.demo", size)
            p = ctx.new_page()
            errs = []
            p.on("pageerror", lambda e: errs.append(str(e)[:200]))
            p.on("response", lambda r: r.status >= 400 and "/api/" in r.url and errs.append(f"{r.status} {r.url[-60:]}"))
            p.goto(a.base + "/analyst.html", wait_until="networkidle")
            p.evaluate("() => document.querySelector(`nav [data-tab='companies']`).click()")
            p.wait_for_selector("[data-co-card]", timeout=15000)
            card = p.locator("details.co-dropdown", has_text="Nimbus Mobility").first
            card.locator("summary.co-summary").click()
            card.locator("[data-co-profile]").click()
            p.wait_for_selector(".cp-tracker", timeout=15000)
            text = card.inner_text()
            check("Demo Ventures tracker" in text and "Staff only" in text and "Service providers and patents" in text, f"{size}: staff see the shared fields and the tracker")
            card.locator("[data-cp='tracker-edit']").click()
            card.locator(".cp-tracker-form [name='fundraise_status']").fill("Series B: term sheet stage (browser check)")
            card.locator(".cp-tracker-form [name='kyc_received']").select_option("yes")
            card.locator(".cp-tracker-form [type='submit']").click()
            p.wait_for_timeout(800)
            check("term sheet stage (browser check)" in card.inner_text(), f"{size}: staff edit and save the tracker")
            card.locator("[data-cp='tracker-edit']").click()
            card.locator(".cp-tracker-form [name='action_points']").fill("Founder PAN ABCDE1234F")
            card.locator(".cp-tracker-form [type='submit']").click()
            p.wait_for_timeout(800)
            check(card.locator(".cp-tracker-form").count() == 1, f"{size}: a PAN number is refused and the form stays open")
            errs[:] = [e for e in errs if "422" not in e]  # the refused save above is expected
            check(p.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"), f"{size}: staff profile has no sideways scrolling")
            if shots:
                card.screenshot(path=str(shots / f"staff-{size}.png"))
            check(not errs, f"{size}: staff page has no errors {errs[:2]}")
            ctx.close()
            # Founder: own profile shows the shared fields and no tracker
            ctx = ctx_for(b, "riya@nimbus.demo", size)
            p = ctx.new_page()
            errs = []
            p.on("pageerror", lambda e: errs.append(str(e)[:200]))
            p.on("response", lambda r: r.status >= 400 and "/api/" in r.url and errs.append(f"{r.status} {r.url[-60:]}"))
            p.goto(a.base + "/", wait_until="networkidle")
            p.evaluate("() => document.querySelector(`[data-page='company']`)?.click()")
            p.wait_for_selector(".cp", timeout=15000)
            body = p.inner_text("body")
            check("Service providers and patents" in body and "Demat status" in body and "Demo Ventures tracker" not in body
                  and "browser check" not in body, f"{size}: founder sees the shared fields and no tracker")
            p.click("[data-cp='edit']")
            p.wait_for_selector("form.cp-form")
            p.fill("form.cp-form [name='patents_filed']", "5")
            p.fill("form.cp-form [name='patents_granted']", "2")
            p.fill("form.cp-form [name='cloud_provider']", "AWS")
            p.locator("form.cp-form [type='submit']").first.click()
            p.wait_for_timeout(900)
            check(p.locator("form.cp-form").count() == 0 and "Patents filed" in p.inner_text("body"), f"{size}: founder edits and saves the new fields")
            check(p.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"), f"{size}: founder profile has no sideways scrolling")
            if shots:
                p.screenshot(path=str(shots / f"founder-{size}.png"), full_page=False)
            check(not errs, f"{size}: founder page has no errors {errs[:2]}")
            ctx.close()
        b.close()
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
