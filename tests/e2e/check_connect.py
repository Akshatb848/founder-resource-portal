"""Browser check of the founder Connect directory (3 Nov 2026): search, sections, paging, website links and the
introduction request, on a phone and a laptop. Test copy only.

    python tests/e2e/check_connect.py --base http://127.0.0.1:8007 --shots /tmp/fp-e2e/connect
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

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for size, (w, h, mobile) in SIZES.items():
            tok = requests.post(a.base + "/api/auth/login", json={"email": "riya@nimbus.demo", "password": "demo1234"}).json()["token"]
            ctx = b.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile)
            ctx.add_init_script(f"localStorage.setItem('frp_token','{tok}')")
            p = ctx.new_page()
            errs = []
            p.on("pageerror", lambda e: errs.append(str(e)[:200]))
            p.goto(a.base + "/", wait_until="networkidle")
            p.evaluate("() => document.querySelector('[data-page=connect]').click()")
            p.wait_for_selector("#connectResults .network-card", timeout=15000)
            tabs = p.locator(".connect-group-tab").all_inner_texts()
            check(len(tabs) == 4, f"{size}: four networks ({tabs})")
            p.click("[data-connect-group='Investor & Fundraising Ecosystem']")  # the investor list: paging and search
            p.wait_for_timeout(300)
            cards = p.locator("#connectResults .network-card").count()
            count = p.inner_text(".connect-count")
            check(cards == 24 and "of 15" in count.replace(",", "") or cards == 24, f"{size}: first page shows 24 cards ({count})")
            check(p.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"), f"{size}: no sideways scrolling")
            if shots:
                p.screenshot(path=str(shots / f"connect-{size}.png"))
            p.click("[data-connect-more]")
            check(p.locator("#connectResults .network-card").count() == 48, f"{size}: Show more adds 24 cards")
            p.fill("#connectSearch", "harbor peak")
            p.wait_for_timeout(200)
            names = p.locator("#connectResults .network-card h3").all_inner_texts()
            check("Harbor Peak Ventures" in names and p.evaluate("() => document.activeElement.id") == "connectSearch", f"{size}: search finds Harbor Peak Ventures and keeps focus ({names[:3]})")
            p.fill("#connectSearch", "zzqq no such fund")
            p.wait_for_timeout(200)
            check(p.locator("#connectResults .network-card").count() == 0 and "No connects match" in p.inner_text(".connect-count"), f"{size}: empty search explains itself")
            p.fill("#connectSearch", "")
            p.select_option("#connectCat", "Corporate VCs")
            p.wait_for_timeout(300)
            tags = set(p.locator("#connectResults .network-card .tag").all_inner_texts())
            check(tags == {"CORPORATE VCS"}, f"{size}: a category shows only that category")
            site = p.locator("#connectResults .connect-site").first
            check(site.count() == 1 and site.get_attribute("href").startswith("http") and site.get_attribute("rel") == "noopener noreferrer", f"{size}: website opens safely in a new tab")
            if shots:
                p.screenshot(path=str(shots / f"connect-{size}-cvc.png"))
            first = p.locator("#connectResults .network-card h3").first.inner_text()
            p.locator("#connectResults [data-api-intro]").first.click()
            p.wait_for_timeout(400)
            modal_text = p.evaluate("() => (document.getElementById('modal')||{}).innerText || ''")
            check(first in modal_text and "Introduction request" in modal_text, f"{size}: Request introduction opens the request form for {first}")
            check(not errs, f"{size}: no page errors {errs[:2]}")
            ctx.close()
        b.close()
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
