#!/usr/bin/env bash
# scripts/overnight.sh — Chain evals + D-Cloaked generation overnight
# Run from WSL2 Ubuntu: bash /mnt/c/Dev/Determinex/scripts/overnight.sh
set -euo pipefail

DETERMINEX="/mnt/c/Dev/Determinex"
LOG_DIR="$DETERMINEX/logs/swebench"
TMP="/mnt/c/tmp"
REPOS="T:/determinex-swebench"

cd "$DETERMINEX"

# Load API keys from .env
set -a
source .env
set +a

log() { echo "[OVERNIGHT] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$TMP/overnight.log"; }

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
    # Print final counts from log
    grep -E "Evaluation: 100%|Total instances:|✓|✖|error=" "$out_log" | tail -5 || true
}

log "=== Overnight run started ==="

# ── 1. Wait for B-Cloaked corrected (180635) to reach 300 predictions ─────────
BCORR_DIR="$LOG_DIR/determinex_lite_B-FrontierParity-Cloaked_20260430_180635"
BCORR_PRED="$BCORR_DIR/predictions.jsonl"
log "Waiting for B-Cloaked corrected gen to finish..."
while true; do
    count=$(wc -l < "$BCORR_PRED" 2>/dev/null || echo 0)
    if [ "$count" -ge 300 ]; then
        log "B-Cloaked corrected: $count/300 DONE"
        break
    fi
    log "B-Cloaked corrected: $count/300 — sleeping 60s..."
    sleep 60
done

# Wait for the gen Python process to fully exit (it tries to self-eval and fails)
log "Waiting 3 min for gen process to exit cleanly..."
sleep 180

# ── 2. Eval B-Cloaked corrected (180635) ──────────────────────────────────────
eval_run \
    "determinex_lite_B-FrontierParity-Cloaked_20260430_180635" \
    "$BCORR_PRED" \
    "$TMP/eval_bcloaked_corrected_err.log"

# ── 3. Eval hardened B-Cloaked (044441) — already 300/300 ────────────────────
BHARD_PRED="$LOG_DIR/determinex_lite_B-FrontierParity-Cloaked_20260430_044441/predictions.jsonl"
eval_run \
    "determinex_lite_B-FrontierParity-Cloaked_20260430_044441" \
    "$BHARD_PRED" \
    "$TMP/eval_bcloaked_hardened_err.log"

# ── 4. D-Cloaked generation (Claude Sonnet Architect + DeepSeek Builder) ──────
log "Starting D-Cloaked generation (Claude Sonnet Architect + DeepSeek Builder)..."
DETERMINEX_DEEPSEEK_KEY="$DEEPSEEK_API_KEY" \
DETERMINEX_ANTHROPIC_KEY="$ANTHROPIC_API_KEY" \
python.exe scripts/determinex_swebench_run.py \
    --split lite \
    --all \
    --repos-dir "$REPOS" \
    --config d \
    --parallel 2 \
    --cloak \
    2>&1 | tee "$LOG_DIR/run_config_d_Cloaked.log"
log "D-Cloaked generation DONE"

# ── 5. Eval D-Cloaked ─────────────────────────────────────────────────────────
D_DIR=$(ls -td "$LOG_DIR"/determinex_lite_D-NuclearHybrid-Cloaked_* 2>/dev/null | head -1 || true)
if [ -n "$D_DIR" ]; then
    D_ID=$(basename "$D_DIR")
    eval_run \
        "$D_ID" \
        "$D_DIR/predictions.jsonl" \
        "$TMP/eval_dcloaked_err.log"
else
    log "ERROR: D-Cloaked run directory not found after generation!"
fi

log "=== All overnight tasks complete! Check $TMP/overnight.log for summary ==="
