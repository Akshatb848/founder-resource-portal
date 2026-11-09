"""Publish researched sector news as Sector Updates for the portfolio companies.

    python backend/scripts/import_sector_news.py            # shows what would change, changes nothing
    python backend/scripts/import_sector_news.py --apply    # publishes the news and withdraws the sample briefs

What goes where: backend/data/demo_sector_news.json. In the public copy the items are fictional briefs with
placeholder links; in a real deployment each item is an article (the link opened and checked when researched) with a summary and, per company, a short note on what it means for that
company, written in our own words. One Sector Update is published per item and company, so each founder sees
the note written for their company, plus a link to the original article.

Safe on any database, including one marked as real data:
- an item is skipped for a company that already has an update with the same article link;
- the seeded sample briefs (source "... (sample brief)", never published by a person) are withdrawn by
  setting them to expired; nothing is deleted, and updates written by the team are never touched;
- every change is written to the audit trail.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import POSTGRES_CONFIG  # noqa: E402
from backend.db import get_conn  # noqa: E402

MANIFEST = ROOT / "backend" / "data" / "demo_sector_news.json"
LABELS = {"POLICY", "REGULATORY", "MARKET", "FUNDING", "TECHNOLOGY"}
ACTOR = "content-import"  # audit actor: this script, run at the Super Admin's request
PUBLISHER = "Demo Ventures research desk"
VISIBLE_DAYS = 90  # each update stays on the founder's page for 90 days after this import
IST = timezone(timedelta(hours=5, minutes=30))


def load(path: Path) -> list[dict]:
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    for it in items:
        missing = [k for k in ("companies", "label", "title", "summary", "why", "source", "source_url", "published") if not it.get(k)]
        if missing:
            raise SystemExit(f"{it.get('title', '?')}: missing {', '.join(missing)}")
        if it["label"] not in LABELS:
            raise SystemExit(f"{it['title']}: label must be one of {sorted(LABELS)}")
        if not it["source_url"].startswith("https://"):
            raise SystemExit(f"{it['title']}: the article link must start with https://")
        for name in it["companies"]:
            if not it["why"].get(name):
                raise SystemExit(f"{it['title']}: no note for {name}")
    return items


def run(apply: bool, path: Path) -> None:
    items = load(path)
    published, skipped, unknown = [], [], set()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, sector FROM companies")
            companies = {r[1]: (r[0], r[2]) for r in cur.fetchall()}
            cur.execute(
                """SELECT id, title FROM sector_updates
                   WHERE source LIKE %s AND published_by IS NULL AND (expires_at IS NULL OR expires_at > NOW())""",
                ("%(sample brief)",),
            )
            samples = cur.fetchall()
            for it in items:
                when = datetime.strptime(it["published"], "%Y-%m-%d").replace(hour=9, tzinfo=IST)
                for name in it["companies"]:
                    if name not in companies:
                        unknown.add(name)
                        continue
                    cid, sector = companies[name]
                    cur.execute("SELECT 1 FROM sector_updates WHERE company_id = %s AND source_url = %s", (cid, it["source_url"]))
                    if cur.fetchone():
                        skipped.append(f"{name}: {it['title']}")
                        continue
                    published.append(f"{name}: {it['title']}")
                    if not apply:
                        continue
                    cur.execute(
                        """INSERT INTO sector_updates (company_id, label, title, summary, sector, source, source_url,
                               published_by, why, approval, published_at, expires_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'approved', %s, NOW() + make_interval(days => %s))""",
                        (cid, it["label"], it["title"], it["summary"], sector, it["source"], it["source_url"],
                         PUBLISHER, it["why"][name], when, VISIBLE_DAYS),
                    )
                    cur.execute(
                        "INSERT INTO admin_audit (actor, action, target, details) VALUES (%s, %s, %s, %s)",
                        (ACTOR, "update.import", it["title"], json.dumps({"company": name, "source_url": it["source_url"]})),
                    )
            if apply:
                for sid, title in samples:
                    cur.execute("UPDATE sector_updates SET expires_at = NOW() WHERE id = %s", (sid,))
                    cur.execute(
                        "INSERT INTO admin_audit (actor, action, target, details) VALUES (%s, %s, %s, %s)",
                        (ACTOR, "update.withdraw", title, json.dumps({"reason": "sample brief replaced by real news"})),
                    )
        if apply:
            conn.commit()
    print(f"Database: {POSTGRES_CONFIG['dbname']} | news from {path.name}")
    print(f"{'Published' if apply else 'Would publish'} {len(published)} updates; {len(skipped)} already there.")
    print(f"{'Withdrew' if apply else 'Would withdraw'} {len(samples)} sample briefs: {', '.join(t for _, t in samples) or 'none'}")
    if unknown:
        print(f"Companies not found (check the name): {', '.join(sorted(unknown))}")
    if not apply:
        print("Nothing changed. Run again with --apply.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--file", type=Path, default=MANIFEST)
    a = p.parse_args()
    run(a.apply, a.file)
