"""Remove sample and test content from a database (partner review, 4 Nov 2026): sample events, the sample
opening and candidate profile, and sample sector briefs. Real content is never touched: only rows marked
is_sample, or sector updates whose source says "(sample brief)" and that no staff member published.

    python -m backend.scripts.remove_samples            dry run: what would be removed
    python -m backend.scripts.remove_samples --apply    removes them
"""
from __future__ import annotations

import sys

from backend.db import get_conn

CHECKS = [
    ("sample events", "SELECT COUNT(*) FROM events WHERE is_sample",
     ["DELETE FROM event_rsvps WHERE event_id IN (SELECT id FROM events WHERE is_sample)", "DELETE FROM events WHERE is_sample"]),
    ("sample candidate profiles", "SELECT COUNT(*) FROM talent_profiles WHERE is_sample",
     ["DELETE FROM talent_profiles WHERE is_sample"]),
    ("sample openings", "SELECT COUNT(*) FROM hiring_roles WHERE is_sample AND NOT EXISTS (SELECT 1 FROM talent_profiles p WHERE p.role_id = hiring_roles.id)",
     ["DELETE FROM hiring_roles WHERE is_sample AND NOT EXISTS (SELECT 1 FROM talent_profiles p WHERE p.role_id = hiring_roles.id)"]),
    ("sample sector briefs", "SELECT COUNT(*) FROM sector_updates WHERE source LIKE '%(sample brief)' AND published_by IS NULL",
     ["DELETE FROM sector_updates WHERE source LIKE '%(sample brief)' AND published_by IS NULL"]),
]


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for label, count_sql, deletes in CHECKS:
                cur.execute(count_sql)
                n = cur.fetchone()[0]
                print(f"{label}: {n}")
                if apply and n:
                    for sql in deletes:
                        cur.execute(sql)
        if apply:
            conn.commit()
    print("Removed." if apply else "Dry run: add --apply to remove them.")


if __name__ == "__main__":
    main()
