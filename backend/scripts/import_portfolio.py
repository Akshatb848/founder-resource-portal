"""Add every portfolio company in the data file to the portal, in fund order (Fund I, II, III, IV).

    python backend/scripts/import_portfolio.py            # shows what would change, changes nothing
    python backend/scripts/import_portfolio.py --apply    # adds the missing companies and fills empty details

Data: backend/data/demo_portfolio.json (fictional demo companies for the public copy).
Safe on any database, including one marked as real data: it only adds companies that are missing and fills
details that are empty (or still hold the alpha's earlier placeholder sector). It never changes a detail
someone edited, never creates accounts, and assigns no fund team (do that in Companies & founders).
Companies marked as exited are added as exited. Each new company gets the starter playbook tasks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.config import POSTGRES_CONFIG  # noqa: E402
from backend.db import get_conn  # noqa: E402
from backend.playbook import seed_template_tasks, sync_progress  # noqa: E402

DATA = ROOT / "backend" / "data" / "demo_portfolio.json"
# Sector text the alpha seeded before the full portfolio was loaded (replaced by the site's sector tags).
EARLIER_SECTORS = {"EV / Energy", "AdTech / MarketingTech", "HealthTech / AI", "AgriTech / AI", "EnterpriseTech / Telecom"}
FIELDS = ("sector", "city", "fund", "invested", "about", "website")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def run(apply: bool) -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))["companies"]
    added, filled, unchanged = [], [], []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for c in sorted(data, key=lambda x: x["order"]):
                values = {"sector": c["sector"] or None, "city": c["city"] or None, "fund": c["fund"] or None,
                          "invested": c["invested"] or None, "about": c["about"] or None, "website": c["website"] or None}
                status = "exited" if c["status"].lower() == "exited" else "active"
                slug = slugify(c["name"])
                cur.execute("SELECT id, slug, sector, city, fund, invested, about, website FROM companies WHERE slug = %s OR lower(name) = lower(%s)",
                            (slug, c["name"]))
                row = cur.fetchone()
                if not row:
                    added.append(f"{c['order']:>2}. {c['name']} ({c['fund']}{', exited' if status == 'exited' else ''})")
                    if apply:
                        cur.execute(
                            """
                            INSERT INTO companies (slug, name, sector, city, fund, invested, about, website, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                            """,
                            (slug, c["name"], *[values[f] for f in FIELDS], status),
                        )
                        cid = cur.fetchone()[0]
                        seed_template_tasks(cur, cid, created_by="Portfolio import")
                        sync_progress(cur, cid)
                    continue
                cid, current = row[0], dict(zip(FIELDS, row[2:]))
                fill = {f: values[f] for f in FIELDS if values[f] and (not current[f] or (f == "sector" and current[f] in EARLIER_SECTORS))}
                fill = {f: v for f, v in fill.items() if v != current[f]}
                if fill:
                    filled.append(f"{c['order']:>2}. {c['name']}: {', '.join(sorted(fill))}")
                    if apply:
                        for f, v in fill.items():  # field names come from FIELDS
                            cur.execute(f"UPDATE companies SET {f} = %s WHERE id = %s", (v, cid))
                else:
                    unchanged.append(c["name"])
        if apply:
            conn.commit()
    print(f"Database: {POSTGRES_CONFIG['dbname']} · {'APPLIED' if apply else 'dry run (add --apply to make the changes)'}")
    print(f"\nNew companies ({len(added)}), in fund order:")
    print("\n".join(added) or "  none")
    print(f"\nExisting companies with empty details filled ({len(filled)}):")
    print("\n".join(filled) or "  none")
    print(f"\nAlready complete ({len(unchanged)}): {', '.join(unchanged) or 'none'}")


def main() -> None:
    run("--apply" in sys.argv[1:])


if __name__ == "__main__":
    main()
