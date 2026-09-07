#!/usr/bin/env bash
# Quick scripted-expert demos across difficulty tiers (no dataset write).
#
# Usage:
#   bash scripts/run_expert_demo.sh
#   BACKEND=amdgpu bash scripts/run_expert_demo.sh
#   MODE=hard EPISODES=2 bash scripts/run_expert_demo.sh
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_dotenv

BACKEND="${BACKEND:-cpu}"
EPISODES="${EPISODES:-1}"
MODE="${MODE:-mix}"   # mix | basic | hard
SEED="${SEED:-0}"

section "Expert demos (mode=$MODE backend=$BACKEND)"

run_py -m radeonvla.setup_assets

case "$MODE" in
  basic)
    TASKS=(banana_white_left lemon_blue_left plum_white_right)
    ;;
  hard)
    TASKS=(leftmost_to_white_left seq_banana_white_left_lemon_white_right rule_red_blue_left_orange_blue_right seq_triple_sort)
    ;;
  mix|*)
    TASKS=(banana_white_left apple_blue_left seq_apple_blue_left_orange_blue_right)
    ;;
esac

FAIL=0
for i in "${!TASKS[@]}"; do
  t="${TASKS[$i]}"
  section "demo $((i+1))/${#TASKS[@]}: $t"
  if ! run_py -m radeonvla.expert \
      --backend "$BACKEND" \
      --task "$t" \
      --episodes "$EPISODES" \
      --seed $((SEED + i)); then
    log "WARN: task $t had failures (exit non-zero)"
    FAIL=$((FAIL + 1))
  fi
done

if [[ "$FAIL" -gt 0 ]]; then
  log "Finished with $FAIL task(s) reporting failures (experts can be flaky; OK for demos)"
  exit 0
fi
ok "All expert demos succeeded"
