#!/usr/bin/env bash
# Fast end-to-end smoke (1 episode): assets -> scene -> expert -> record -> validate -> train dry-run
#
# Usage:
#   bash scripts/run_pipeline_smoke.sh
#   BACKEND=cpu bash scripts/run_pipeline_smoke.sh
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

BACKEND="${BACKEND:-cpu}"
START=$(date +%s)

section "Pipeline smoke (backend=$BACKEND)"
run_py -m radeonvla.pipeline all-smoke \
  --backend "$BACKEND" \
  --episodes 1 \
  --task banana_white_left \
  --repo-id visiobot/radeonvla_reflex_smoke \
  --dataset-root datasets/radeonvla_reflex_smoke \
  --device cpu \
  --overwrite \
  --discard-incomplete \
  --dry-run-train

ok "Smoke finished in $(elapsed "$START")s"
