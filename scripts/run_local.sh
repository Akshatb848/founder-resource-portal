#!/usr/bin/env bash
# Run the portal locally (Linux/macOS) against a PostgreSQL you already have.
#   cp backend/.env.example backend/.env    # then set PG_* for your database
#   ./scripts/run_local.sh                  # venv, deps, dist/, schema + demo data, API on :8000
#   ./scripts/run_local.sh --no-seed        # skip loading demo data
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
VENV="${VENV:-.venv}"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q -r backend/requirements.txt
[ -f backend/.env ] || { echo "Create backend/.env from backend/.env.example first (PG_* settings)."; exit 1; }
"$VENV/bin/python" scripts/sync_dist.py
if [ "${1:-}" != "--no-seed" ]; then
  PORTAL_SAMPLES="${PORTAL_SAMPLES:-1}" "$VENV/bin/python" -m backend.seed
  "$VENV/bin/python" backend/scripts/import_portfolio.py --apply >/dev/null
  "$VENV/bin/python" backend/scripts/import_sector_news.py --apply >/dev/null
fi
echo "Founder's Resource Portal on http://127.0.0.1:${PORT:-8000}  (demo logins in README.md)"
exec "$VENV/bin/uvicorn" backend.main:app --host 127.0.0.1 --port "${PORT:-8000}"
