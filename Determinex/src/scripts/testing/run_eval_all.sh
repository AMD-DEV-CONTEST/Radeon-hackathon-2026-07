#!/usr/bin/env bash
# scripts/testing/run_eval_all.sh — Submit completed prediction sets to SWE-bench Docker eval harness
# DEPRECATED for production use — prefer runpod/run_swebench_eval.sh on a CPU pod
# (see runpod/RUNPOD_SWEBENCH_EVAL.md). This local-WSL variant is kept for
# debug/smoke-testing individual prediction files only.
#
# Run from WSL2: wsl -d Ubuntu bash /mnt/c/Dev/Determinex/scripts/testing/run_eval_all.sh
# Or from Windows Git Bash (invokes WSL internally via wsl -d Ubuntu python3 -m ...)
#
# Prerequisites:
#   - swebench installed in WSL2 Ubuntu (pip install swebench)
#   - Docker Desktop running
#   - Predictions complete for each run dir below
#
# Runs eval sequentially to avoid RAM pressure from parallel Docker builds.
# Each eval: ~4-8 hours for 300 instances at --max_workers 4.

set -euo pipefail

LOG_DIR="/mnt/c/Dev/Determinex/logs/swebench"
RESULTS_DIR="/mnt/c/Dev/Determinex/logs/swebench/eval_results"
mkdir -p "$RESULTS_DIR"

log() { echo "[EVAL] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$RESULTS_DIR/eval_all.log"; }

run_eval() {
    local name="$1"
    local run_dir="$LOG_DIR/$2"
    local pred="$run_dir/predictions.jsonl"
    local run_id="$2"

    if [ ! -f "$pred" ]; then
        log "SKIP $name — predictions.jsonl not found at $pred"
        return
    fi

    local count
    count=$(wc -l < "$pred")
    if [ "$count" -lt 300 ]; then
        log "SKIP $name — only $count/300 predictions (generation incomplete)"
        return
    fi

    log "========================================"
    log "START eval: $name ($count predictions)"
    log "========================================"
    python3 -m swebench.harness.run_evaluation \
        --dataset_name princeton-nlp/SWE-bench_Lite \
        --split test \
        --predictions_path "$pred" \
        --max_workers 4 \
        --run_id "$run_id" \
        2>&1 | tee "$RESULTS_DIR/${name}.log"
    log "DONE: $name"
    echo ""

    # Extract summary line
    grep -E "Resolved|resolved|Total instances|✓|✗" "$RESULTS_DIR/${name}.log" | tail -10 || true
}

log "=== SWE-bench Eval: All Ablation Configs ==="
log "Running sequentially to avoid Docker image build conflicts"

# ── 1. B-Uncloaked (post-hardening) ──────────────────────────────────────────
run_eval "b-uncloaked-post-hardening" \
    "determinex_20260505_1145_lite_B-FrontierParity_ablation_b-uncloaked-post-hardening"

# ── 2. E-RegionControl ────────────────────────────────────────────────────────
run_eval "e-regioncontrol" \
    "determinex_20260506_0816_lite_E-RegionControl_ablation_e-regioncontrol"

# ── 3. B-Cloaked (Rosetta OFF) ────────────────────────────────────────────────
run_eval "b-cloaked-rosetta-off" \
    "determinex_20260506_0653_lite_B-FrontierParity-Cloaked_ablation_b-cloaked-rosetta-off"

# ── 4. D-Cloaked (post-hardening) ────────────────────────────────────────────
run_eval "d-cloaked-post-hardening" \
    "determinex_20260506_0807_lite_D-NuclearHybrid-Cloaked_ablation_d-cloaked-post-hardening"

log "========================================"
log "ALL EVALS COMPLETE"
log "Results in: $RESULTS_DIR/"
log ""
log "Score delta:"
log "  B-Uncloaked:     X/300 = X%  (frontier baseline)"
log "  E-RegionControl: R/300 = R%  (R-X = region mode benefit)"
log "  B-Cloaked:       Y/300 = Y%  (R-Y = sovereignty cost)"
log "  D-Cloaked:       Z/300 = Z%  (Z-Y = Claude architect lift)"
log "========================================"
