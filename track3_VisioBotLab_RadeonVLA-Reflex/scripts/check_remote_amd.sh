#!/usr/bin/env bash
# Strict AMD environment gate + short scene/benchmark smoke
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
BACKEND="${BACKEND:-amdgpu}"
START=$(date +%s)

section "Remote AMD checks (HIP_VISIBLE_DEVICES=$HIP_VISIBLE_DEVICES)"

run_py -m radeonvla.check_env \
  --require-amd \
  --init-genesis \
  --json artifacts/environment.remote.json

run_py -m radeonvla.setup_assets
run_py -m radeonvla.scene --backend "$BACKEND" --steps 50 --save-frames
run_py -m radeonvla.benchmark --backend "$BACKEND" --steps 200
run_py -m radeonvla.submission_audit

ok "Remote AMD checks passed in $(elapsed "$START")s"
