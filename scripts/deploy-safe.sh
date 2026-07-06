#!/usr/bin/env bash
# Safe CapRover deploy: ships code only — never bundles or overwrites server DB.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Safe deploy checklist ==="
echo "✓ Local data/places.db is gitignored (not in image)"
echo "✓ Server DB lives in CapRover persistent volume: /captain/data"
echo "✓ Auto-seed only runs when server DB is empty (unless GMAPS_SKIP_SEED=1)"
echo ""
echo "DO NOT run ./scripts/copy-db-to-seed.sh before deploy"
echo "     (that would bake your local DB into the image seed)"
echo ""

if git diff --quiet seed/places.db 2>/dev/null; then
  echo "✓ seed/places.db unchanged in git"
else
  echo "⚠ WARNING: seed/places.db has uncommitted changes."
  echo "  If you commit it, redeploy won't overwrite server data UNLESS"
  echo "  the server DB is empty or you call seed-database?force=true."
  echo "  Skip: git restore seed/places.db"
  read -r -p "Continue anyway? [y/N] " ans
  [[ "${ans:-}" =~ ^[Yy]$ ]] || exit 1
fi

if ! command -v caprover >/dev/null 2>&1; then
  echo ""
  echo "caprover CLI not found. Use Git push instead:"
  echo "  git push origin main"
  echo "Then CapRover → Force rebuild (with persistent dir /captain/data set)."
  exit 0
fi

APP="${CAPROVER_APP:-waleef-gmaps}"
TARBALL="/tmp/waleef-gmaps-deploy-$$.tar.gz"

tar -czf "$TARBALL" \
  --exclude='.venv' \
  --exclude='data' \
  --exclude='output' \
  --exclude='.git' \
  captain-definition Dockerfile requirements.txt setup.py \
  seed/places.db gmaps_scraper_server scripts

echo ""
echo "Deploying to CapRover app: $APP"
caprover deploy -t "$TARBALL" -a "$APP"
rm -f "$TARBALL"

echo ""
echo "After deploy, verify on CapRover:"
echo "  1. Persistent directory: /captain/data"
echo "  2. Env: GMAPS_DATA_DIR=/captain/data"
echo "  3. Env: GMAPS_SKIP_SEED=1  (recommended if server already has data)"
echo "  4. curl https://YOUR-APP/health"
