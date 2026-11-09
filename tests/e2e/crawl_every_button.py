"""End-to-end sanity crawl: sign in as each role, open every page/tab, click every visible control, fill and
submit every form a click opens, and record every error (page errors, console errors, failed requests,
error toasts). Runs ONLY against the test copy (refuses unless /api/health says data == "demo").

    python tests/e2e/crawl_every_button.py --base http://127.0.0.1:8001 --roles founder analyst admin
    python tests/e2e/crawl_every_button.py --roles super_admin --out /tmp/fp-e2e/crawl

Output: <out>/<role>.json (every action and what happened) and screenshots of failures.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import Error as PwError
from playwright.sync_api import sync_playwright

ACCOUNTS = {  # demo accounts that exist only in the test database (seed.py)
    "founder": ("riya@nimbus.demo", "/", "page"),
    "analyst": ("analyst@team.demo", "/analyst.html", "tab"),
    "admin": ("manager@team.demo", "/analyst.html", "tab"),
    "super_admin": ("superadmin@team.demo", "/analyst.html", "tab"),
}
PASSWORD = "demo1234"
SKIP_TEXT = re.compile(r"^(sign out|log out|logout)$", re.I)
CLICKABLE = ("button, a[href], [data-action], [role=button], summary, [data-page]:not(nav [data-page]), "
             "[data-goto], [data-filter], input[type=checkbox], input[type=radio]")
SAMPLE_FILE = Path(__file__).resolve().parents[2] / "content" / "alpha" / "fundraising-checklist.docx"  # any small file to upload

ENUM_JS = """(sel) => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('.hidden,[hidden]')
      && r.left < innerWidth && r.right > 0                       // off-screen (a closed drawer) is not clickable
      && !(e.closest('details:not([open])') && !e.closest('summary'))   // inside a collapsed section: not shown
      && (!window.__crawlScope || window.__crawlScope.contains(e)); };
  const out = []; const seen = {};
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e) || e.disabled) continue;
    if (e.closest('nav, .sidebar nav')) continue;              // navigation is visited as pages/tabs
    const txt = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\\s+/g, ' ').slice(0, 70);
    const attrs = ['data-action','data-id','data-tab','data-page','data-goto','data-filter','href','name','type']
      .map(a => e.getAttribute(a) ? a + '=' + e.getAttribute(a) : '').filter(Boolean).join(' ');
    const sig = e.tagName.toLowerCase() + '|' + txt + '|' + attrs;
    seen[sig] = (seen[sig] || 0) + 1;
    out.push({sig, n: seen[sig] - 1, txt, href: e.getAttribute('href') || '', target: e.getAttribute('target') || '',
              inModal: !!e.closest('#modal:not(.hidden), .modal, [role=dialog]')});
  }
  return out;
}"""

FIND_JS = """([sel, sig, n]) => {
  let k = 0;
  for (const e of document.querySelectorAll(sel)) {
    if (e.closest('nav, .sidebar nav')) continue;
    const r = e.getBoundingClientRect(); if (!(r.width > 0 && r.height > 0) || e.closest('.hidden,[hidden]') || e.disabled) continue;
    if (!(r.left < innerWidth && r.right > 0) || (window.__crawlScope && !window.__crawlScope.contains(e))) continue;
    if (e.closest('details:not([open])') && !e.closest('summary')) continue;
    const txt = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\\s+/g, ' ').slice(0, 70);
    const attrs = ['data-action','data-id','data-tab','data-page','data-goto','data-filter','href','name','type']
      .map(a => e.getAttribute(a) ? a + '=' + e.getAttribute(a) : '').filter(Boolean).join(' ');
    if (e.tagName.toLowerCase() + '|' + txt + '|' + attrs === sig) { if (k === n) { e.setAttribute('data-crawl-target', '1'); return true; } k++; }
  }
  return false;
}"""

MODAL_OPEN_JS = """() => { const m = document.querySelector('#modal:not(.hidden) .modal, #modal:not(.hidden), dialog[open], [role=dialog]:not(.hidden)');
  if (!m) return false; const r = m.getBoundingClientRect(); return r.width > 0 && r.height > 0; }"""

ERROR_UI_JS = """() => [...document.querySelectorAll('.toast.show, .toast, .error, .alert, [role=alert], .notice.error, .form-error, .intake-error')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map(e => e.innerText.trim())
  .filter(t => t && (/\\b(error|failed|could not|went wrong|not found|denied|invalid|unable|exception|traceback)\\b/i.test(t)
                     || /\\b(undefined|null|NaN|\\[object Object\\])\\b/.test(t)))"""


def login(base: str, email: str) -> str:
    r = requests.post(base + "/api/auth/login", json={"email": email, "password": PASSWORD}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


class Recorder:
    def __init__(self):
        self.events: list[dict] = []

    def attach(self, page, base):
        page.on("pageerror", lambda e: self.events.append({"kind": "pageerror", "text": str(e)[:500]}))
        page.on("console", lambda m: m.type == "error" and self.events.append({"kind": "console", "text": m.text[:500]}))
        page.on("dialog", lambda d: (self.events.append({"kind": "dialog", "text": d.message[:300]}), d.accept()))

        def on_resp(r):
            if r.url.startswith(base) and r.status >= 400:
                self.events.append({"kind": "http", "status": r.status, "url": r.url.replace(base, ""), "method": r.request.method})
        page.on("response", on_resp)
        page.on("requestfailed", lambda r: r.url.startswith(base) and self.events.append(
            {"kind": "requestfailed", "url": r.url.replace(base, ""), "text": (r.failure or "")[:200]}))

    def take(self):
        ev, self.events = self.events, []
        return ev


def fill_form(page, scope=None) -> list[str]:
    """Fill every visible empty field inside the open modal (or the given form) with test values. Returns notes."""
    notes = []
    if scope is None:
        scope = page.locator("#modal:not(.hidden), dialog[open], [role=dialog]:not(.hidden)").first
        if not scope.count():
            scope = page.locator("body")
    if scope.locator("input[type=password]").count():
        notes.append("password form: not submitted (would change a test account's password mid-crawl)")
        return notes
    today = dt.date.today()
    for inp in scope.locator("input:visible, textarea:visible, select:visible").all():
        try:
            tag = inp.evaluate("e => e.tagName.toLowerCase()")
            typ = (inp.get_attribute("type") or "text").lower()
            if tag == "select":
                opts = inp.locator("option").all()
                vals = [o.get_attribute("value") for o in opts if (o.get_attribute("value") or o.inner_text().strip())]
                if inp.input_value() in ("", None) and len(vals) > 1:
                    inp.select_option(index=1)
                continue
            if typ in ("checkbox", "radio"):
                if not inp.is_checked() and inp.get_attribute("name") and \
                        not scope.locator(f"input[name='{inp.get_attribute('name')}']:checked").count():
                    inp.check()
                continue
            if typ == "file":
                inp.set_input_files(str(SAMPLE_FILE))
                continue
            if typ in ("hidden", "submit", "button", "search") or inp.input_value():
                continue
            mn = int(inp.get_attribute("minlength") or 0)
            val = {
                "email": "crawl.test@example.com", "url": "https://example.com/crawl", "tel": "9876543210",
                "number": inp.get_attribute("min") or "5", "date": (today + dt.timedelta(days=7)).isoformat(),
                "datetime-local": (dt.datetime.now() + dt.timedelta(days=7)).strftime("%Y-%m-%dT10:00"),
                "time": "10:00", "month": today.strftime("%Y-%m"),
            }.get(typ, "Crawler test entry for end-to-end sanity")
            if len(val) < mn:
                val = (val + " ") * (mn // len(val) + 1)
            mx = inp.get_attribute("maxlength")
            if mx and mx.isdigit():
                val = val[: int(mx)]
            inp.fill(val)
        except PwError as e:
            notes.append(f"fill skipped: {str(e).splitlines()[0][:120]}")
    return notes


def submit_in_modal(page) -> str | None:
    """Click the primary/submit button of the open modal once. Returns its label."""
    for sel in ("#modal:not(.hidden) button[type=submit]", "#modal:not(.hidden) .btn.primary",
                "dialog[open] button[type=submit]", "[role=dialog] button[type=submit]", "[role=dialog] .btn.primary"):
        b = page.locator(sel).filter(has_not_text=re.compile("cancel|close", re.I))
        for i in range(b.count()):
            if b.nth(i).is_visible() and b.nth(i).is_enabled():
                label = b.nth(i).inner_text().strip()[:60]
                b.nth(i).click(timeout=4000)
                return label
    return None


def crawl_role(pw, base: str, role: str, out: Path, headless: bool = True, only_views=None) -> dict:
    email, start, mode = ACCOUNTS[role]
    token = login(base, email)
    browser = pw.chromium.launch(headless=headless)
    ctx = browser.new_context(viewport={"width": 1366, "height": 800}, accept_downloads=True)
    ctx.add_init_script(f"try{{localStorage.setItem('frp_token','{token}')}}catch(e){{}}")
    page = ctx.new_page()
    ctx.on("page", lambda p: p != page and p.close())  # links that open a new tab: keep the crawl on one page
    rec = Recorder()
    rec.attach(page, base)
    results = {"role": role, "email": email, "views": {}, "actions": []}

    downloads = []
    page.on("download", lambda d: downloads.append(d))
    # Extra "views" that sit behind an opener rather than a nav item: (name, nav view, opener, scope)
    extra = {"founder": [("notifications", "dashboard", "#notifyBtn", "#notificationPanel")]}.get(role, [])

    def open_view(view: str | None):
        try:
            page.goto(base + start, wait_until="networkidle")
        except PwError:  # one slow load (busy test machine) gets a second chance; a second failure is reported
            page.goto(base + start, wait_until="networkidle", timeout=60000)
        # Collapsible menu groups (Founder support) start closed: open them so their tabs are reachable.
        page.evaluate("() => document.querySelectorAll('.group-toggle[aria-expanded=false]').forEach(b => b.click())")
        target, opener, scope = view, None, None
        for name, nav, op, sc in extra:
            if view == name:
                target, opener, scope = nav, op, sc
        if target:
            page.locator(f"[data-{mode}='{target}']").first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(350)
        # Companies & founders: every company is a closed dropdown; open them all so their controls are reachable.
        page.evaluate("() => document.querySelectorAll('details.co-dropdown').forEach(d => { d.open = true; })")
        if opener:
            page.locator(opener).first.click()
            page.wait_for_timeout(600)
        page.evaluate("(sc) => { window.__crawlScope = sc ? document.querySelector(sc) : null; }", scope)

    def settle(ms=700):
        page.wait_for_timeout(ms)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PwError:
            pass

    open_view(None)
    rec.take()
    views = page.evaluate(f"() => [...document.querySelectorAll('[data-{mode}]')].filter(e => e.closest('nav') && "
                          f"e.getBoundingClientRect().width > 0 && !e.closest('.hidden')).map(e => e.dataset.{mode})")
    views = list(dict.fromkeys(views)) + [x[0] for x in extra]
    if only_views:
        views = [v for v in views if v in only_views]
    print(f"[{role}] views: {views}", flush=True)
    for view in views:
        try:
            open_view(view)
        except PwError as e:
            results["views"][view] = {"controls": 0, "load_errors": [{"kind": "load", "text": str(e).splitlines()[0][:200]}]}
            print(f"[{role}] {view}: could not load ({str(e).splitlines()[0][:120]})", flush=True)
            continue
        load_errors = rec.take()
        items = page.evaluate(ENUM_JS, CLICKABLE)
        results["views"][view] = {"controls": len(items), "load_errors": load_errors}
        print(f"[{role}] {view}: {len(items)} controls, load errors {len(load_errors)}", flush=True)
        for it in items:
            if SKIP_TEXT.match(it["txt"]):
                continue
            act = {"view": view, "control": it["txt"] or it["sig"], "sig": it["sig"]}
            href = it["href"]
            if href and not href.startswith("#") and not href.startswith("/") and not href.startswith(base) \
                    and not href.startswith("javascript"):
                act["result"] = f"external link, not followed: {href[:120]}"
                act["ok"] = bool(re.match(r"^(https?://|mailto:|tel:)", href))
                results["actions"].append(act)
                continue
            try:
                open_view(view)
                rec.take()
                if not page.evaluate(FIND_JS, [CLICKABLE, it["sig"], it["n"]]):
                    act["result"] = "control not present after reload (dynamic list)"
                    act["ok"] = True
                    results["actions"].append(act)
                    continue
                tgt = page.locator("[data-crawl-target='1']").first
                tgt.scroll_into_view_if_needed(timeout=3000)
                # A submit button of a form on the page: fill the form first, like a person would.
                is_submit = tgt.evaluate("e => !!e.closest('form') && (e.type === 'submit' || "
                                         "(e.tagName === 'BUTTON' && !e.getAttribute('type')))")
                if is_submit and not tgt.evaluate("e => !!e.closest('#modal, [role=dialog]')"):
                    act["notes"] = fill_form(page, tgt.locator("xpath=ancestor::form[1]"))
                    act["form_filled"] = True
                n_dl = len(downloads)
                try:
                    tgt.click(timeout=4000)
                except PwError as e:
                    act["click_error"] = str(e).splitlines()[0][:200]
                settle()
                if len(downloads) > n_dl:
                    dl = downloads[-1]
                    act["download"] = dl.suggested_filename
                    act["download_failure"] = dl.failure()
                if page.evaluate(MODAL_OPEN_JS):
                    act["modal"] = True
                    act["notes"] = act.get("notes", []) + fill_form(page)
                    if not any("password form" in n for n in act["notes"]):
                        label = submit_in_modal(page)
                        if label:
                            act["submitted"] = label
                            settle(900)
                act["ui_errors"] = page.evaluate(ERROR_UI_JS)
                toasts = page.evaluate("() => [...document.querySelectorAll('.toast.show, #toast.show')]"
                                       ".map(e => e.innerText.trim()).filter(Boolean)")
                if toasts:
                    act["toasts"] = toasts
                fake = [t for t in toasts if re.search(r"simulated|demonstrated|demo only|not connected yet", t, re.I)]
                if fake:
                    act["ui_errors"] = act["ui_errors"] + [f"mock-only action: {t}" for t in fake]
            except PwError as e:
                act["crawl_error"] = str(e).splitlines()[0][:200]
            act["events"] = rec.take()
            # A confirmation prompt ("Cancel this event?") is intended behaviour; it is accepted and recorded only.
            bad = [e for e in act["events"] if e["kind"] not in ("http", "dialog") or (e["kind"] == "http" and e["status"] >= 400)]
            act["ok"] = not (bad or act.get("ui_errors") or act.get("click_error") or act.get("download_failure")
                             or act.get("crawl_error"))
            if not act["ok"]:
                shot = out / f"{role}-{len(results['actions']):04d}.png"
                try:
                    page.screenshot(path=str(shot))
                    act["screenshot"] = str(shot)
                except PwError:
                    pass
            results["actions"].append(act)
    browser.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--roles", nargs="+", default=list(ACCOUNTS))
    ap.add_argument("--out", type=Path, default=Path("/tmp/fp-e2e/crawl"))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--views", nargs="*", help="only these pages/tabs (default: all)")
    a = ap.parse_args()
    h = requests.get(a.base + "/api/health", timeout=10).json()
    if h.get("data") != "demo":
        sys.exit(f"Refusing: {a.base} reports data={h.get('data')}. Run this only against the test copy.")
    a.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        for role in a.roles:
            t0 = time.time()
            res = crawl_role(pw, a.base, role, a.out, headless=not a.headed, only_views=a.views)
            (a.out / f"{role}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
            fails = [x for x in res["actions"] if not x.get("ok")]
            loads = sum(len(v["load_errors"]) for v in res["views"].values())
            print(f"[{role}] done in {time.time() - t0:.0f}s: {len(res['actions'])} actions, {len(fails)} with problems, "
                  f"{loads} page-load errors", flush=True)


if __name__ == "__main__":
    main()
