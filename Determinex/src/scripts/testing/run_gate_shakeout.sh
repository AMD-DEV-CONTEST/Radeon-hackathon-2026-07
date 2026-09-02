#!/usr/bin/env bash
# scripts/run_gate_shakeout.sh
#
# Compile-gate shakeout: 3 instances per language × all supported languages.
# Purpose: shake out gate bugs, Cloak interactions, and language-specific
# compile/test failures before running the full 300-instance ablation.
#
# Config: D-Cloaked (Claude Sonnet 4.6 Architect + DeepSeek V3 Builder + Cloak ON)
# All patches are compile-gate verified before acceptance.
#
# Usage:
#   bash scripts/run_gate_shakeout.sh
#   bash scripts/run_gate_shakeout.sh --workers 2
#   bash scripts/run_gate_shakeout.sh --split multiswe   # use MultiSWE-bench instead
#
# Monitor live:
#   tail -f logs/swebench/gate_shakeout_*/run.log
#   ls logs/swebench/gate_shakeout_*/gate_wal/
#   ls logs/swebench/gate_shakeout_*/gate_escalations/

set -euo pipefail

PARALLEL=${PARALLEL:-4}
SPLIT=${SPLIT:-multilingual}   # multilingual (9 langs) or multiswe (7 langs)
INSTANCES_PER_LANG=${INSTANCES_PER_LANG:-3}

# Parse flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --parallel) PARALLEL="$2"; shift 2 ;;
        --split)    SPLIT="$2";    shift 2 ;;
        --n)        INSTANCES_PER_LANG="$2"; shift 2 ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

if [[ "$SPLIT" == "multilingual" ]]; then
    # SWE-bench Multilingual has no Python — Python comes from SWE-bench Lite
    MULTILINGUAL_LANGS=("javascript" "typescript" "java" "go" "rust" "ruby" "php" "c")
    LANGS=("python" "${MULTILINGUAL_LANGS[@]}")
elif [[ "$SPLIT" == "multiswe" ]]; then
    # multiswe supports: java typescript javascript go rust c cpp
    LANGS=("python" "java" "typescript" "javascript" "go" "rust" "c" "cpp")
else
    LANGS=("python")
fi

echo "=== Determinex Compile-Gate Shakeout ==="
echo "Config:   D-Cloaked (d + --cloak)"
echo "Split:    $SPLIT"
echo "Langs:    ${LANGS[*]}"
echo "N/lang:   $INSTANCES_PER_LANG"
echo "Parallel: $PARALLEL"
echo ""

SHAKEOUT_LOG="logs/gate_shakeout_summary.txt"
mkdir -p logs/swebench
echo "Gate shakeout — $(date)" > "$SHAKEOUT_LOG"
echo "Config: D-Cloaked (d --cloak) | Split: $SPLIT | N=$INSTANCES_PER_LANG per lang" >> "$SHAKEOUT_LOG"
echo "" >> "$SHAKEOUT_LOG"

TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_GATE_ESCALATIONS=0

for LANG in "${LANGS[@]}"; do
    echo "--- [$LANG] running $INSTANCES_PER_LANG instances ---"

    RUN_ID="gate_shakeout_${LANG}_$(date +%Y%m%d_%H%M%S)"

    # Python lives in SWE-bench Lite; all other langs in multilingual
    if [[ "$LANG" == "python" ]]; then
        LANG_SPLIT="lite"
    else
        LANG_SPLIT="$SPLIT"
    fi

    # Run with Cloak enabled, language-filtered, instance count capped
    mkdir -p "logs/swebench/${RUN_ID}"
    python scripts/determinex_swebench_run.py \
        --config b \
        --cloak \
        --split "$LANG_SPLIT" \
        --lang "$LANG" \
        --instances "$INSTANCES_PER_LANG" \
        --parallel "$PARALLEL" \
        --run-id "$RUN_ID" \
        2>&1 | tee "logs/swebench/${RUN_ID}/run.log" || true

    # Collect per-lang stats
    PRED_FILE="logs/swebench/${RUN_ID}/predictions.jsonl"
    GATE_WAL_DIR="logs/swebench/${RUN_ID}/gate_wal"
    ESC_DIR="logs/swebench/${RUN_ID}/gate_escalations"

    LANG_PATCHED=0
    LANG_EMPTY=0
    if [[ -f "$PRED_FILE" ]]; then
        LANG_PATCHED=$(python -c "
import json, sys
with open('$PRED_FILE') as f:
    rows = [json.loads(l) for l in f if l.strip()]
print(sum(1 for r in rows if r.get('model_patch','').strip()))
" 2>/dev/null || echo 0)
        LANG_EMPTY=$(python -c "
import json, sys
with open('$PRED_FILE') as f:
    rows = [json.loads(l) for l in f if l.strip()]
print(sum(1 for r in rows if not r.get('model_patch','').strip()))
" 2>/dev/null || echo 0)
    fi

    LANG_WAL_COUNT=0
    if [[ -d "$GATE_WAL_DIR" ]]; then
        LANG_WAL_COUNT=$(ls "$GATE_WAL_DIR"/*.jsonl 2>/dev/null | wc -l || echo 0)
    fi

    LANG_ESC_COUNT=0
    if [[ -d "$ESC_DIR" ]]; then
        LANG_ESC_COUNT=$(ls "$ESC_DIR"/*.json 2>/dev/null | wc -l || echo 0)
    fi

    TOTAL_PASS=$((TOTAL_PASS + LANG_PATCHED))
    TOTAL_FAIL=$((TOTAL_FAIL + LANG_EMPTY))
    TOTAL_GATE_ESCALATIONS=$((TOTAL_GATE_ESCALATIONS + LANG_ESC_COUNT))

    LANG_LINE="[$LANG] patched=$LANG_PATCHED empty=$LANG_EMPTY gate_wal=$LANG_WAL_COUNT escalations=$LANG_ESC_COUNT"
    echo "  $LANG_LINE"
    echo "$LANG_LINE" >> "$SHAKEOUT_LOG"
done

echo ""
echo "=== SHAKEOUT SUMMARY ==="
echo "Total patched:          $TOTAL_PASS"
echo "Total empty:            $TOTAL_FAIL"
echo "Gate escalations:       $TOTAL_GATE_ESCALATIONS"
echo ""
echo "Gate WAL training data: logs/swebench/gate_shakeout_*/gate_wal/"
echo "Escalations (need fix): logs/swebench/gate_shakeout_*/gate_escalations/"
echo ""
echo "Full summary: $SHAKEOUT_LOG"

echo "" >> "$SHAKEOUT_LOG"
echo "TOTAL: patched=$TOTAL_PASS empty=$TOTAL_FAIL escalations=$TOTAL_GATE_ESCALATIONS" >> "$SHAKEOUT_LOG"
