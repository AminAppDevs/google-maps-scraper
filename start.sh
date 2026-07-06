#!/usr/bin/env bash
# One command to start the scraper web UI (no Docker).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "First-time setup..."
  ./scripts/setup.sh
fi

source .venv/bin/activate

# Playwright browsers must be in ~/Library/Caches/ms-playwright (not installed in sandbox setup)
./scripts/ensure-playwright.sh

echo ""
echo "  Google Maps Scraper"
echo "  Open in browser: http://localhost:8001"
echo ""
exec uvicorn gmaps_scraper_server.main_api:app --host 127.0.0.1 --port 8001 --reload
