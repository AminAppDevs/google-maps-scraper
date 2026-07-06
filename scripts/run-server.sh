#!/usr/bin/env bash
# Start the scraper web UI at http://localhost:8001
set -euo pipefail
exec "$(cd "$(dirname "$0")/.." && pwd)/start.sh"
