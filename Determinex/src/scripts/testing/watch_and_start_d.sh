#!/usr/bin/env bash
# Watch B-Cloaked until 300/300, then auto-launch D-Cloaked.
set -euo pipefail

DETERMINEX="${DETERMINEX_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG_DIR="$DETERMINEX/logs/swebench"
BCLOAKED_PRED="$LOG_DIR/determinex_20260505_2035_lite_B-FrontierParity-Cloaked_ablation_b-cloaked-rosetta-on/predictions.jsonl"
D_LOG="$LOG_DIR/ablation_d_cloaked.log"

cd "$DETERMINEX"
source .env 2>/dev/null || true

log() { echo "[WATCH] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_DIR/chain.log"; }

log "Watching B-Cloaked predictions — waiting for 300/300..."
while true; do
    count=$(wc -l < "$BCLOAKED_PRED" 2>/dev/null || echo 0)
    if [ "$count" -ge 300 ]; then
        log "B-Cloaked complete ($count/300). Launching D-Cloaked now."
        break
    fi
    log "B-Cloaked: $count/300 — sleeping 60s..."
    sleep 60
done

sleep 10  # let the B process exit cleanly

log "Starting D-Cloaked (Claude Sonnet Architect + DeepSeek Builder, Cloak ON)..."
DETERMINEX_ARCHITECT_BACKEND=anthropic \
DETERMINEX_BUILDER_BACKEND=deepseek \
DETERMINEX_CLOAK=1 \
python scripts/determinex_swebench_run.py \
    --config d \
    --cloak \
    --parallel 2 \
    --all \
    --run-type ablation \
    --skip-eval \
    >> "$D_LOG" 2>&1

log "D-Cloaked generation complete. Check $D_LOG for results."
