#!/usr/bin/env bash
# Copy local scraped DB into seed/ for CapRover deploy (bundled in Docker image).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/data/places.db"
DEST="$ROOT/seed/places.db"
if [[ ! -f "$SRC" ]]; then
  echo "No database at $SRC — run a scrape first."
  exit 1
fi
mkdir -p "$ROOT/seed"
cp "$SRC" "$DEST"
COUNT=$(python3 -c "import sqlite3; print(sqlite3.connect('$DEST').execute('SELECT COUNT(*) FROM places').fetchone()[0])")
echo "Seed updated: $DEST ($COUNT places, $(du -h "$DEST" | cut -f1))"
