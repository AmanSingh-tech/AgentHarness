#!/usr/bin/env bash
# One static website: the showcase site at /, and the dashboard at /app/ in recorded-demo mode (it
# replays real runs from dashboard/public/demo/, so no API server is needed).
#
#   bash scripts/build_static.sh                         -> .vercel-out/          (root vercel.json)
#   bash ../scripts/build_static.sh dashboard/.vercel-out  (dashboard/vercel.json, Root Directory = dashboard)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$(pwd)/${1:-.vercel-out}"
rm -rf "$OUT"
mkdir -p "$OUT"
cp -r site/. "$OUT/"
rm -f "$OUT/vercel.json"
(cd dashboard && npm ci --no-audit --no-fund && VITE_DEMO=1 npx vite build --base=/app/ --outDir "$OUT/app" --emptyOutDir)
echo "built $OUT: site at /, dashboard (recorded demo) at /app/"
