#!/usr/bin/env bash
# Local setup (no n8n, no Docker). Run from repo root: ./scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "==> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -e . --no-deps

echo "==> Installing Playwright Chromium..."
./scripts/ensure-playwright.sh

echo ""
echo "Setup complete. Start the web UI:"
echo "  ./start.sh"
echo "  Then open http://localhost:8001"
