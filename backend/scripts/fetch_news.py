"""Fetch approved sector-news feeds once and create suggestions.

    python -m backend.scripts.fetch_news

For the VM: run from a systemd timer or cron every 15 minutes and set NEWS_FETCH_ENABLED=0 for the API,
so only one scheduler is active. Running both is still safe (a database lock prevents overlap).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.news_feed import run_cycle  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_cycle("cli")
    print(result)
    sys.exit(0 if result.get("status") in ("ok", "busy") else 1)
