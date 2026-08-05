#!/bin/bash
# master_dsl_finetune.sh
# DSL fine-tuning: Observer v5 → Engineer v10 → Sentinel v4-dsl
# Sequential. Stop between models to run micro_eval locally and decide accept/rollback.
#
# ── Prerequisites on pod ───────────────────────────────────────────────────────
#   /workspace/data/dsl_corpus.jsonl      (upload from local scripts/dsl_corpus.jsonl)
#   /workspace/data/curriculum.jsonl      (already present from prior training)
#   /workspace/data/gap_v3_arc_mutex.jsonl
#   /workspace/data/gap_v3_go_panic.jsonl
#   /workspace/data/gap_v4_observer_specific.jsonl
#   /workspace/data/gap_v4_sentinel_specific.jsonl
#   /workspace/llama.cpp/                 (already present)
#   dsl_finetune.py                       (upload from local scripts/dsl_finetune.py)
#
# ── STEP 0 — Capture pre-DSL baselines LOCALLY (run on local machine FIRST) ──
# These numbers go in the white paper and become the before/after comparison.
# Run these BEFORE starting the pod, while local Ollama has the current models.
#
#   # Observer pre-DSL baseline
#   python scripts/micro_eval.py --model determinex-observer-v4 --save-baseline
#   cp logs/eval_results/baseline.json logs/eval_results/pre_dsl_observer_v4.json
#
#   # Engineer pre-DSL baseline
#   python scripts/micro_eval.py --model determinex-engineer-v9 --save-baseline
#   cp logs/eval_results/baseline.json logs/eval_results/pre_dsl_engineer_v9.json
#
#   # Sentinel pre-DSL baseline
#   python scripts/micro_eval.py --model determinex-sentinel-v3 --save-baseline
#   cp logs/eval_results/baseline.json logs/eval_results/pre_dsl_sentinel_v3.json
#
#   # Verify all three captured (expected: Observer 78%, Engineer 84%, Sentinel 87%)
#   for f in logs/eval_results/pre_dsl_*.json; do
#     echo "$f:"; python -c "import json,sys; d=json.load(open(sys.argv[1])); print('  ',d['overall_pct'],'%')" "$f"
#   done
#
# ── Upload commands (run on LOCAL machine before starting pod) ─────────────────
#   scp -P PORT -i ~/.ssh/id_runpod scripts/dsl_finetune.py root@POD_IP:/workspace/
#   scp -P PORT -i ~/.ssh/id_runpod scripts/dsl_corpus.jsonl root@POD_IP:/workspace/data/
#
# Watch progress:
#   tail -f /workspace/dsl_finetune.log
#
# ── Rollback rules (plan Gap 5) ───────────────────────────────────────────────
#   delta >= 0%            → ACCEPT. Run next model.
#   delta -1% to 0%        → ACCEPT with note.
#   delta -1% to -3%       → Re-run with LORA_R=4 (edit dsl_finetune.py line ~41)
#   delta < -3% at rank 4  → REJECT. Skip this model's DSL fine-tune.
#
# ── Post-fine-tune eval (run locally after downloading each GGUF) ─────────────
# After each SCP download below, register the model with Ollama and run:
#   ollama create determinex-observer-v5 -f backend/agents/modelfiles/Modelfile.observer_v5
#   python scripts/micro_eval.py --model determinex-observer-v5 --compare \
#     --baseline logs/eval_results/pre_dsl_observer_v4.json
#   cp logs/eval_results/latest.json logs/eval_results/post_dsl_observer_v5.json
#
# Repeat for engineer-v10 and sentinel-v4-dsl with their respective baseline files.

LOG=/workspace/dsl_finetune.log
exec > >(tee -a "$LOG") 2>&1

echo ""
echo "============================================================"
echo "  DSL FINE-TUNE: Observer → Engineer → Sentinel"
echo "  Started: $(date)"
echo "  LoRA rank: 8 | Epochs: 3 | Max seq: 512"
echo "============================================================"

# ── Verify prerequisites ───────────────────────────────────────────────────────
echo ""
echo "[PRE-FLIGHT] Checking prerequisites..."

MISSING=0
for f in /workspace/data/dsl_corpus.jsonl /workspace/data/curriculum.jsonl /workspace/llama.cpp/convert_hf_to_gguf.py /workspace/dsl_finetune.py; do
    if [ ! -f "$f" ]; then
        echo "  [MISSING] $f"
        MISSING=1
    else
        echo "  [OK] $f"
    fi
done

if [ $MISSING -eq 1 ]; then
    echo ""
    echo "[FAIL] Prerequisites missing. Upload before running."
    exit 1
fi

DSL_COUNT=$(wc -l < /workspace/data/dsl_corpus.jsonl)
echo "  DSL corpus: $DSL_COUNT pairs"
if [ "$DSL_COUNT" -lt 200 ]; then
    echo "  [WARN] Low DSL pair count — expected 800+. Fine-tune may be weak."
fi

echo "[PRE-FLIGHT] OK"

# ── STAGE A: Observer v5 ──────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  [A/C] OBSERVER v5 (Llama 3.2 3B)"
echo "  Started: $(date)"
echo "============================================================"

python3 /workspace/dsl_finetune.py observer 2>&1 | tee /workspace/dsl_obs_v5.log
OBS_EXIT=${PIPESTATUS[0]}

if [ $OBS_EXIT -ne 0 ]; then
    echo "[FAIL] Observer DSL fine-tune exited $OBS_EXIT. Check dsl_obs_v5.log"
    exit 1
fi

echo ""
echo "============================================================"
echo "  Observer v5 DONE — $(date)"
echo "  STOP HERE. Run micro_eval locally before proceeding."
echo ""
echo "  scp -P PORT -i ~/.ssh/id_runpod \\"
echo "    root@POD_IP:/workspace/outputs/determinex-observer-v5/determinex-observer-v5.gguf \\"
echo "    '${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions/observer/v5-dsl/determinex-observer-v5.gguf'"
echo ""
echo "  Then run: python scripts/micro_eval.py --model determinex-observer-v5"
echo "  Compare delta against Observer v4 baseline (78%)."
echo "  Apply rollback rules, then resume this script or re-run with rank 4."
echo "============================================================"

# ── Disk cleanup before Engineer ──────────────────────────────────────────────
echo ""
echo "[CLEANUP] Clearing Llama 3.2 cache before Engineer download..."
du -sh ~/.cache/huggingface/hub/models--meta-llama* 2>/dev/null || echo "  No Llama cache found."
rm -rf ~/.cache/huggingface/hub/models--meta-llama*
echo "  Root disk after cleanup:"
df -h /
echo "[CLEANUP] Done."

# ── STAGE B: Engineer v10 ────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  [B/C] ENGINEER v10 (Qwen2.5-Coder 1.5B)"
echo "  Started: $(date)"
echo "============================================================"

python3 /workspace/dsl_finetune.py engineer 2>&1 | tee /workspace/dsl_eng_v10.log
ENG_EXIT=${PIPESTATUS[0]}

if [ $ENG_EXIT -ne 0 ]; then
    echo "[FAIL] Engineer DSL fine-tune exited $ENG_EXIT. Check dsl_eng_v10.log"
    exit 1
fi

echo ""
echo "============================================================"
echo "  Engineer v10 DONE — $(date)"
echo "  STOP HERE. Run micro_eval locally before proceeding."
echo ""
echo "  scp -P PORT -i ~/.ssh/id_runpod \\"
echo "    root@POD_IP:/workspace/outputs/determinex-engineer-v10/determinex-engineer-v10.gguf \\"
echo "    '${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions/engineer/v10-dsl/determinex-engineer-v10.gguf'"
echo ""
echo "  Then run: python scripts/micro_eval.py --model determinex-engineer-v10"
echo "  Compare delta against Engineer v9 baseline (84%)."
echo "============================================================"

# ── Disk cleanup before Sentinel ─────────────────────────────────────────────
echo ""
echo "[CLEANUP] Clearing Qwen cache before Sentinel download..."
rm -rf ~/.cache/huggingface/hub/models--Qwen*
echo "  Root disk after cleanup:"
df -h /
echo "[CLEANUP] Done."

# ── STAGE C: Sentinel v4-dsl ─────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  [C/C] SENTINEL v4-dsl (Mistral 7B)"
echo "  Started: $(date)"
echo "============================================================"

python3 /workspace/dsl_finetune.py sentinel 2>&1 | tee /workspace/dsl_sen_v4.log
SEN_EXIT=${PIPESTATUS[0]}

if [ $SEN_EXIT -ne 0 ]; then
    echo "[FAIL] Sentinel DSL fine-tune exited $SEN_EXIT. Check dsl_sen_v4.log"
    exit 1
fi

echo ""
echo "============================================================"
echo "  ALL DSL FINE-TUNES DONE — $(date)"
echo ""
echo "  Download Sentinel GGUF:"
echo "  scp -P PORT -i ~/.ssh/id_runpod \\"
echo "    root@POD_IP:/workspace/outputs/determinex-sentinel-v4-dsl/determinex-sentinel-v4-dsl.gguf \\"
echo "    '${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions/sentinel/v4-dsl/determinex-sentinel-v4-dsl.gguf'"
echo ""
echo "  Then run: python scripts/micro_eval.py --model determinex-sentinel-v4-dsl"
echo "  Compare delta against Sentinel v3 baseline (87%)."
echo ""
echo "  All three models trained. Apply rollback decisions, register accepted"
echo "  models with Ollama, update litellm_config.yaml role assignments."
echo "============================================================"
