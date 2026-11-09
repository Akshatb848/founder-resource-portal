"""The Connect directory: investors, operational partners, peer founders and the fund's own network.

    python -m backend.scripts.import_connects            dry run: what --apply would change
    python -m backend.scripts.import_connects --apply    makes the database's Connect directory exactly that list

The list lives in backend/data/demo_connects.json. In this public copy every organisation and person in it is
fictional. Only organisation-level facts go into the portal: name, category, location, website, sectors and
stages; founders reach a connect through an introduction request, which the fund team handles.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_FILE = ROOT / "backend" / "data" / "demo_connects.json"
GROUP = "Investor & Fundraising Ecosystem"


def load() -> list[dict]:
    """Every Connect entry in the data file."""
    entries = json.loads(DATA_FILE.read_text(encoding="utf-8"))["connects"]
    for e in entries:
        e.setdefault("network_group", GROUP)
    return entries


def apply_connects(cur, entries: list[dict], dry_run: bool = False, keep_staff_added: bool = False) -> dict[str, int]:
    """Make the Connect directory exactly `entries`. Entries that founders asked to be introduced to are
    hidden rather than deleted, so their requests keep their history. The list's entries are system entries
    (created_by empty); keep_staff_added (used when seeding demo data) leaves profiles staff added by hand."""
    from backend.sqlutil import q

    names = [e["display_name"] for e in entries]
    cur.execute(q("SELECT id, display_name, EXISTS (SELECT 1 FROM founder_help h WHERE h.connect_entry_id = e.id), created_by FROM connect_entries e"))
    existing = cur.fetchall()
    keep = set(names)
    stats = {"added": 0, "updated": 0, "removed": 0, "hidden": 0}
    for cid, name, referenced, created_by in existing:
        if name in keep or (keep_staff_added and created_by):
            continue
        if referenced:
            stats["hidden"] += 1
            if not dry_run:
                cur.execute(q("UPDATE connect_entries SET active = FALSE WHERE id = %s"), (cid,))
        else:
            stats["removed"] += 1
            if not dry_run:
                cur.execute(q("DELETE FROM connect_entries WHERE id = %s"), (cid,))
    have = {n for _, n, _, _ in existing}
    for e in entries:
        vals = (e.get("network_group", GROUP), e["subcategory"], e["role_title"], e["organization"], e["about"], e["skills"],
                e["website"] or None, e.get("stage") or None, e.get("cheque") or None)
        if e["display_name"] in have:
            stats["updated"] += 1
            if not dry_run:
                cur.execute(
                    q("""UPDATE connect_entries SET network_group = %s, subcategory = %s, role_title = %s, organization = %s,
                         why_relevant = %s, skills = %s, website = %s, stage = %s, cheque_size = %s, is_sample = FALSE,
                         active = TRUE, approval = 'approved' WHERE display_name = %s"""),
                    vals + (e["display_name"],),
                )
        else:
            stats["added"] += 1
            if not dry_run:
                cur.execute(
                    q("""INSERT INTO connect_entries (network_group, subcategory, role_title, organization, why_relevant, skills,
                         website, stage, cheque_size, display_name, is_sample, active, approval)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, TRUE, 'approved')"""),
                    vals + (e["display_name"],),
                )
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the list to the database")
    args = ap.parse_args()
    from backend.db import get_conn

    entries = load()
    with get_conn() as conn:
        with conn.cursor() as cur:
            stats = apply_connects(cur, entries, dry_run=not args.apply)
        if args.apply:
            conn.commit()
    verb = "Applied" if args.apply else "Dry run (use --apply to write)"
    print(f"{verb}: {len(entries)} connects; added {stats['added']}, updated {stats['updated']}, "
          f"removed {stats['removed']}, hidden (have requests) {stats['hidden']}")


if __name__ == "__main__":
    main()
