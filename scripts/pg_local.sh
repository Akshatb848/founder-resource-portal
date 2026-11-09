#!/usr/bin/env bash
# Throw-away PostgreSQL for development/tests, without Docker (needs PostgreSQL 14+ binaries on PATH,
# e.g. /usr/lib/postgresql/16/bin on Debian/Ubuntu or `brew install postgresql@16`).
#   ./scripts/pg_local.sh start   # data in ${PGDATA_DIR:-./.pgdata}, port ${PG_PORT:-5433}
#   ./scripts/pg_local.sh stop
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="${PGDATA_DIR:-$PWD/.pgdata}"; PORT="${PG_PORT:-5433}"
case "${1:-start}" in
  start)
    if [ ! -f "$DATA/PG_VERSION" ]; then
      initdb -D "$DATA" -A trust -U postgres >/dev/null
      pg_ctl -D "$DATA" -o "-p $PORT -c listen_addresses=127.0.0.1 -k /tmp" -l "$DATA/log.txt" -w start
      psql -h 127.0.0.1 -p "$PORT" -U postgres -c "CREATE ROLE fp_local LOGIN PASSWORD 'change-me'" \
        -c "CREATE DATABASE founder_portal_local OWNER fp_local" -c "CREATE DATABASE founder_portal_test OWNER fp_local"
    else
      pg_ctl -D "$DATA" -o "-p $PORT -c listen_addresses=127.0.0.1 -k /tmp" -l "$DATA/log.txt" -w start
    fi
    echo "PostgreSQL on 127.0.0.1:$PORT (databases founder_portal_local, founder_portal_test; user fp_local)";;
  stop) pg_ctl -D "$DATA" -w stop;;
  *) echo "usage: $0 start|stop"; exit 2;;
esac
