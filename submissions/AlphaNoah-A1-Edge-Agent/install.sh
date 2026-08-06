#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo "Python 3 is required."; exit 1; }
command -v node >/dev/null || { echo "Node.js is required."; exit 1; }
command -v npm >/dev/null || { echo "npm is required."; exit 1; }
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || { echo "Python 3.11+ is required."; exit 1; }
npm --prefix "$ROOT_DIR/frontend" ci
echo "AlphaNoah dependencies ready."
