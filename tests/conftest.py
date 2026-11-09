"""Shared test setup.

Unit tests need no database. Integration tests in test_api_integration.py run only when
FP_TEST_DB=1 and PG_* variables point at a throw-away Postgres database (CI provides one).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Never start the background news fetcher (network access) from tests.
os.environ.setdefault("NEWS_FETCH_ENABLED", "0")
