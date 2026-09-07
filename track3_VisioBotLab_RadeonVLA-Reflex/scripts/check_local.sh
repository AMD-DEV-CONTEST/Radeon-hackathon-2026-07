#!/usr/bin/env bash
# Local quality gate: environment report + release audit + pytest + ruff.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

START=$(date +%s)
section "Local checks"

run_py -m radeonvla.check_env --json docs/environment.local.json
run_py -m radeonvla.submission_audit
run_py -m pytest
if command -v ruff >/dev/null 2>&1; then
  run ruff check src tests
else
  run_py -m ruff check src tests
fi

ok "Local checks passed in $(elapsed "$START")s"
