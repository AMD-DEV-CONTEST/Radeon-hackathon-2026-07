#!/usr/bin/env bash
# scripts/testing/run_chain.sh — Overnight ablation chain (waits for B-Uncloaked, then chains all remaining)
# Usage: bash scripts/testing/run_chain.sh
# Runs: B-Cloaked → B-Cloaked/NoRosetta → E-RegionControl → D-Cloaked
# B-Uncloaked is assumed to already be running.

set -euo pipefail

DETERMINEX="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$DETERMINEX"

set -a
source .env
set +a

REPOS="T:/determinex-swebench"
PARALLEL=4
LOG_DIR="logs/swebench"

log() { echo "[CHAIN] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a logs/swebench/chain.log; }

run() {
    local label="$1"; shift
    log "========================================"
    log "START: $label"
    log "========================================"
    python scripts/determinex_swebench_run.py \
        --split lite --all \
        --repos-dir "$REPOS" \
        --parallel "$PARALLEL" \
        --skip-eval \
        "$@"
    log "DONE: $label"
}

# Wait for B-Uncloaked to finish before starting the chain
BUNC_LOG="logs/swebench/ablation_b_uncloaked.log"
log "Waiting for B-Uncloaked to complete..."
while true; do
    done_count=$(grep -c "DONE" "$BUNC_LOG" 2>/dev/null || echo 0)
    if [ "$done_count" -ge 300 ]; then
        log "B-Uncloaked complete ($done_count/300). Starting chain."
        break
    fi
    log "B-Uncloaked: $done_count/300 done — sleeping 120s..."
    sleep 120
done

# ── 1. B-Cloaked (Rosetta ON) ─────────────────────────────────────────────────
run "B-Cloaked (Rosetta ON)" \
    --config b --cloak \
    --run-type ablation --name b-cloaked-rosetta-on \
    >> logs/swebench/ablation_b_cloaked.log 2>&1

# ── 2. B-Cloaked (Rosetta OFF) ────────────────────────────────────────────────
DETERMINEX_NO_ROSETTA=1 \
run "B-Cloaked (Rosetta OFF)" \
    --config b --cloak \
    --run-type ablation --name b-cloaked-rosetta-off \
    >> logs/swebench/ablation_b_cloaked_norosetta.log 2>&1

# ── 3. E-RegionControl ────────────────────────────────────────────────────────
run "E-RegionControl (no cloak, region mode)" \
    --config e \
    --run-type ablation --name e-regioncontrol \
    >> logs/swebench/ablation_e_regioncontrol.log 2>&1

# ── 4. D-Cloaked (Claude Architect + DeepSeek Builder) ───────────────────────
run "D-Cloaked (Claude Architect + DeepSeek Builder)" \
    --config d --cloak \
    --run-type ablation --name d-cloaked-headline \
    >> logs/swebench/ablation_d_cloaked.log 2>&1

log "========================================"
log "ALL RUNS COMPLETE"
log "========================================"
log ""
log "Predictions:"
log "  B-Uncloaked:       logs/swebench/ablation_b_uncloaked.log"
log "  B-Cloaked:         logs/swebench/ablation_b_cloaked.log"
log "  B-Cloaked/NoRos:   logs/swebench/ablation_b_cloaked_norosetta.log"
log "  E-RegionControl:   logs/swebench/ablation_e_regioncontrol.log"
log "  D-Cloaked:         logs/swebench/ablation_d_cloaked.log"
log ""
log "Run Docker eval next (on a RunPod box):"
log "  bash runpod/upload_predictions.sh && ssh \$RUNPOD_HOST 'bash /workspace/run_swebench_eval.sh'"
log "  See runpod/RUNPOD_SWEBENCH_EVAL.md for the full playbook."
