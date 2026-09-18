#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/server_env.sh"
cd "$BG_REPO"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
result_dir="$BG_ARTIFACTS/validation/$timestamp"
mkdir -p "$result_dir"

"$SCRIPT_DIR/server_probe.sh"
"$BG_VENV/bin/python" scripts/verify_rocm_runtime.py \
  | tee "$result_dir/rocm-runtime.json"
"$BG_VENV/bin/buildguard" validate-config --config "$BG_CONFIG" \
  | tee "$result_dir/config-validation.txt"
"$BG_VENV/bin/buildguard" competition-check --config "$BG_CONFIG" --level full \
  | tee "$result_dir/competition-readiness.json"
"$BG_VENV/bin/buildguard" full-stress-check --config "$BG_CONFIG" \
  | tee "$result_dir/full-stress.json"
"$SCRIPT_DIR/health_check.sh" | tee "$result_dir/health.txt"
"$BG_VENV/bin/python" -m pytest -q | tee "$result_dir/pytest.txt"
"$BG_VENV/bin/python" -m ruff check src tests | tee "$result_dir/ruff.txt"
"$BG_VENV/bin/python" -m mypy src | tee "$result_dir/mypy.txt"
"$BG_VENV/bin/python" -m pip check | tee "$result_dir/pip-check.txt"
printf '%s\n' "$result_dir" >"$BG_ARTIFACTS/latest-validation.txt"
echo "Validation evidence: $result_dir"
