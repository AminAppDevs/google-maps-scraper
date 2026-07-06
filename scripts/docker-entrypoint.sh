#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${GMAPS_DATA_DIR:-/captain/data}"
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR" 2>/dev/null || true

export PORT="${PORT:-80}"

python - <<'PY'
import shutil
import sqlite3
from pathlib import Path

from gmaps_scraper_server.database import init_db, DB_PATH, DATA_DIR

SEED = Path("/app/seed/places.db")

init_db()

def place_count(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()

count = place_count(DB_PATH)

if SEED.is_file() and count == 0:
    shutil.copy2(SEED, DB_PATH)
    count = place_count(DB_PATH)
    print(f"Seeded database: {count} places copied from {SEED} -> {DB_PATH}")

print(f"Database ready: {DB_PATH} ({count} places, data dir: {DATA_DIR})")
PY

exec "$@"
