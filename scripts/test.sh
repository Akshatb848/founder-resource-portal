#!/usr/bin/env bash
# Lint + unit tests; add the integration tests with FP_TEST_DB=1 and PG_* pointing at a throw-away database
# whose name ends in _test (the tests seed it and refuse a database marked as real data).
#   ./scripts/test.sh
#   FP_TEST_DB=1 PG_HOST=127.0.0.1 PG_PORT=5433 PG_DB=founder_portal_test PG_USER=fp_local PG_PASSWORD=change-me ./scripts/test.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"; VENV="${VENV:-.venv}"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q -r backend/requirements-dev.txt ruff
"$VENV/bin/ruff" check --select E9,F63,F7,F82 backend tests
NEWS_FETCH_ENABLED=0 "$VENV/bin/pytest" -q
