"""Screen-size check: for every role (founder, analyst, admin, Super Admin), every page and workspace tab must
fit the screen (no sideways scroll) and load without console or page errors, on a phone (375 x 812), a
tablet (768 x 1024) and a laptop (1366 x 768). Runs only against the test copy.

    python tests/e2e/check_mobile_layout.py --base http://127.0.0.1:8001
    python tests/e2e/check_mobile_layout.py --sizes phone      # phone only
"""
from __future__ import annotations

import argparse
import sys

import requests
from playwright.sync_api import sync_playwright

ROLES = {"founder": ("riya@nimbus.demo", "/", "page"), "analyst": ("analyst@team.demo", "/analyst.html", "tab"),
         "admin": ("manager@team.demo", "/analyst.html", "tab"), "super_admin": ("superadmin@team.demo", "/analyst.html", "tab")}
SIZES = {"phone": (375, 812, True), "tablet": (768, 1024, True), "laptop": (1366, 768, False)}

OVERFLOW_JS = """() => {
  const w = document.documentElement.clientWidth;
  const wide = [...document.querySelectorAll('body *')].filter(e => {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    if (!(r.width > 0 && r.height > 0) || s.position === 'fixed' || e.closest('.drawer, .sidebar, .table-wrap, .scroll-x, pre, table')) return false;
    return r.right > w + 1;
  }).slice(0, 5).map(e => (e.tagName + '.' + [...e.classList].join('.')).slice(0, 60) + ' ' + Math.round(e.getBoundingClientRect().right));
  return {scrollWidth: document.documentElement.scrollWidth, width: w, wide};
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--sizes", nargs="+", default=list(SIZES), choices=list(SIZES))
    ap.add_argument("--roles", nargs="+", default=list(ROLES), choices=list(ROLES))
    a = ap.parse_args()
    if requests.get(a.base + "/api/health", timeout=10).json().get("data") != "demo":
        sys.exit("Refusing: run only against the test copy.")
    problems = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for size in a.sizes:
          w_, h_, mobile = SIZES[size]
          for role in a.roles:
            email, start, mode = ROLES[role]
            tok = requests.post(a.base + "/api/auth/login", json={"email": email, "password": "demo1234"}).json()["token"]
            ctx = b.new_context(viewport={"width": w_, "height": h_}, is_mobile=mobile, has_touch=mobile)
            ctx.add_init_script(f"localStorage.setItem('frp_token','{tok}')")
            p = ctx.new_page()
            errs = []
            p.on("pageerror", lambda e: errs.append(str(e)[:200]))
            p.on("console", lambda m: m.type == "error" and errs.append(m.text[:200]))
            p.goto(a.base + start, wait_until="networkidle")
            views = p.evaluate(f"() => [...new Set([...document.querySelectorAll('nav [data-{mode}]')].filter(e => !e.closest('.hidden')).map(e => e.dataset.{mode}))]")
            for v in views:
                errs.clear()
                p.goto(a.base + start, wait_until="networkidle")
                p.evaluate(f"(v) => document.querySelector(`[data-{mode}='${{v}}']`).click()", v)
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(400)
                o = p.evaluate(OVERFLOW_JS)
                bad = o["scrollWidth"] > o["width"] + 1 or errs
                problems += bool(bad)
                print(f"{'FAIL' if bad else 'OK  '} {size:6} {role:11} {v:12} width {o['width']} scroll {o['scrollWidth']} {o['wide'] if o['scrollWidth'] > o['width'] + 1 else ''} {errs[:2]}")
            ctx.close()
        b.close()
    print(f"{problems} pages with problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
