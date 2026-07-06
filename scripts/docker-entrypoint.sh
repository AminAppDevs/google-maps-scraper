#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${GMAPS_DATA_DIR:-/captain/data}"
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR" 2>/dev/null || true

export PORT="${PORT:-80}"

# Initialize SQLite schema on first run (safe if DB already exists).
python - <<'PY'
from gmaps_scraper_server.database import init_db, DB_PATH, DATA_DIR
init_db()
print(f"Database ready: {DB_PATH} (data dir: {DATA_DIR})")
PY

exec "$@"
