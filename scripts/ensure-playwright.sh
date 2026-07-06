#!/usr/bin/env bash
# Ensure Playwright Chromium is installed for the current user.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate

if python - <<'PY'
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser.close()
except Exception:
    raise SystemExit(1)
PY
then
  exit 0
fi

echo "==> Downloading Playwright Chromium (one-time, ~170 MB)..."
playwright install chromium
echo "==> Playwright ready."
