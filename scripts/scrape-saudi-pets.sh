#!/usr/bin/env bash
# Batch scrape pet stores & vet clinics across major Saudi cities.
# Run after setup: ./scripts/scrape-saudi-pets.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate

OUT_DIR="$ROOT/output/saudi-pets-$(date +%Y%m%d)"
mkdir -p "$OUT_DIR"

# Run one query at a time to reduce rate limiting (wait 60s between runs per README)
queries=(
  "pet store Riyadh"
  "veterinary clinic Riyadh"
  "محل حيوانات أليفة الرياض"
  "عيادة بيطرية الرياض"
  "pet store Jeddah"
  "veterinary clinic Jeddah"
  "pet store Dammam"
  "veterinary clinic Dammam"
)

for q in "${queries[@]}"; do
  safe_name="$(echo "$q" | tr ' /' '__' | tr -cd '[:alnum:]_-')"
  echo "==> $q"
  python scripts/scrape.py "$q" --max-places 100 --lang en -o "$OUT_DIR/${safe_name}.json" || true
  echo "Waiting 60s before next query (rate limit)..."
  sleep 60
done

echo "Done. Files in $OUT_DIR"
