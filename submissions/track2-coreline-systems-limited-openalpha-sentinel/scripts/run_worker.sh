#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime optional
cd "$ROOT_DIR"

if [[ ! -x .venv/bin/openalpha ]]; then
  echo "Run scripts/bootstrap_local.sh first." >&2
  exit 1
fi

exec .venv/bin/openalpha worker "$@"
