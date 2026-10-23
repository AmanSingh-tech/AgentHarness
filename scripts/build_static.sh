#!/usr/bin/env bash
# Static deployment (Vercel or any static host): the showcase site at /, and the dashboard at /app/
# in recorded-demo mode (it replays real runs from dashboard/public/demo/, no API server needed).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=.vercel-out
rm -rf "$OUT"
mkdir -p "$OUT"
cp -r site/. "$OUT/"
(cd dashboard && npm ci --no-audit --no-fund && VITE_DEMO=1 npx vite build --base=/app/ --outDir "../$OUT/app" --emptyOutDir)
echo "built $OUT: site at /, dashboard (recorded demo) at /app/"
