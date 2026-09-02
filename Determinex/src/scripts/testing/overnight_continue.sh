#!/usr/bin/env bash
# scripts/overnight_continue.sh — Resume: eval B-Cloaked runs (both at 300/300)
# Run from WSL2 Ubuntu: bash /mnt/c/Dev/Determinex/scripts/overnight_continue.sh
set -euo pipefail

DETERMINEX="/mnt/c/Dev/Determinex"
LOG_DIR="$DETERMINEX/logs/swebench"
TMP="/mnt/c/tmp"

cd "$DETERMINEX"

log() { echo "[OVERNIGHT] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$TMP/overnight_continue.log"; }

eval_run() {
    local run_id="$1"
    local pred_path="$2"
    local out_log="$3"
    local pred_count
    pred_count=$(wc -l < "$pred_path" 2>/dev/null || echo 0)
    log "EVAL START: $run_id ($pred_count predictions)"
    python3 -m swebench.harness.run_evaluation \
        --dataset_name princeton-nlp/SWE-bench_Lite \
        --split test \
        --predictions_path "$pred_path" \
        --max_workers 4 \
        --run_id "$run_id" \
        2>&1 | tee "$out_log"
    log "EVAL DONE: $run_id"
    grep -E "Evaluation: 100%|Total instances:|✓|✖|error=" "$out_log" | tail -5 || true
}

log "=== Continuation run started (both B-Cloaked at 300/300) ==="

# ── 1. Eval B-Cloaked corrected (180635) ──────────────────────────────────────
eval_run \
    "determinex_lite_B-FrontierParity-Cloaked_20260430_180635" \
    "$LOG_DIR/determinex_lite_B-FrontierParity-Cloaked_20260430_180635/predictions.jsonl" \
    "$TMP/eval_bcloaked_corrected_err.log"

# ── 2. Eval B-Cloaked hardened (044441) ──────────────────────────────────────
eval_run \
    "determinex_lite_B-FrontierParity-Cloaked_20260430_044441" \
    "$LOG_DIR/determinex_lite_B-FrontierParity-Cloaked_20260430_044441/predictions.jsonl" \
    "$TMP/eval_bcloaked_hardened_err.log"

log "=== B-Cloaked evals complete. D-Cloaked gen should be running in parallel. ==="
log "=== Check D-Cloaked gen progress: ls -la $LOG_DIR/determinex_lite_D-NuclearHybrid-Cloaked_* ==="
