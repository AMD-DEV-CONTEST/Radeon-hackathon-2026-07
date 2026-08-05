#!/usr/bin/env bash
# build-frontend.sh — Build React frontend (production mode)
#
# Usage: bash scripts/build-frontend.sh
# Output: web/dist/ directory (served by FastAPI static hosting)
set -euo pipefail

WEB_DIR="$(cd "$(dirname "$0")/.." && pwd)/web"
cd "$WEB_DIR"

echo "===== [1/3] Checking Node.js ====="
if ! command -v node >/dev/null 2>&1; then
  echo "  Node.js not installed, installing..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>/dev/null
  apt-get install -y nodejs
fi
echo "  Node: $(node --version)"
echo "  npm:  $(npm --version)"

echo "===== [2/3] Installing dependencies ====="
npm install --silent 2>&1 | tail -3

echo "===== [3/3] Production build ====="
npm run build 2>&1 | tail -10

echo ""
echo "===== Verification ====="
if [ -f "dist/index.html" ]; then
  echo "  [OK] web/dist/index.html exists"
  echo "  Output files:"
  find dist -type f | head -20 | sed 's/^/    /'
  SIZE=$(du -sh dist | awk '{print $1}')
  echo "  Total size: $SIZE"
else
  echo "  [FAIL] web/dist/index.html not found, build failed"
  exit 1
fi
echo "===== done ====="
