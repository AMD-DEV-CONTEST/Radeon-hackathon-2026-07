#!/bin/bash
# master_retrain.sh
# Chains Observer v5 -> Sentinel v4 retrains sequentially,
# verifies all 3 GGUFs on completion, prints DONE when safe to download.
# Watch with: tail -f /workspace/master_retrain.log

LOG=/workspace/master_retrain.log
exec > >(tee -a "$LOG") 2>&1

echo ""
echo "============================================================"
echo "  MASTER RETRAIN: Observer v5 + Sentinel v4"
echo "  Started: $(date)"
echo "============================================================"

# ── STAGE A: Observer retrain ─────────────────────────────────
echo ""
echo "[A/D] Starting Observer retrain (Llama 3.2 3B)..."
python3 /workspace/fix_retrain_observer.py 2>&1 | tee /workspace/retrain_obs_v2.log
OBS_EXIT=${PIPESTATUS[0]}
if [ $OBS_EXIT -ne 0 ]; then
    echo "[FAIL] Observer retrain exited with code $OBS_EXIT. Check retrain_obs_v2.log"
    exit 1
fi
echo "[A/D] Observer retrain DONE."

# ── STAGE B: Disk cleanup between models ─────────────────────
echo ""
echo "[B/D] Disk cleanup — clearing Llama 3.2 cache before Mistral 7B download..."
du -sh ~/.cache/huggingface/hub/models--meta-llama* 2>/dev/null || echo "  No Llama cache found."
rm -rf ~/.cache/huggingface/hub/models--meta-llama--Llama-3.2-3B-Instruct
rm -rf ~/.cache/huggingface/hub/models--Qwen*
echo "  Root disk after cleanup:"
df -h /
echo "[B/D] Cleanup DONE."

# ── STAGE C: Sentinel retrain ────────────────────────────────
echo ""
echo "[C/D] Starting Sentinel retrain (Mistral 7B)..."
python3 /workspace/fix_retrain_sentinel.py 2>&1 | tee /workspace/retrain_sen_v2.log
SEN_EXIT=${PIPESTATUS[0]}
if [ $SEN_EXIT -ne 0 ]; then
    echo "[FAIL] Sentinel retrain exited with code $SEN_EXIT. Check retrain_sen_v2.log"
    exit 1
fi
echo "[C/D] Sentinel retrain DONE."

# ── STAGE D: Verify all 3 GGUFs ─────────────────────────────
echo ""
echo "[D/D] Verifying all 3 GGUFs..."

python3 /workspace/archive/_check_header.py 2>&1

# Engineer (already done)
ENG=/workspace/outputs/determinex-engineer-v9/determinex-engineer-v9.gguf
OBS=/workspace/outputs/determinex-observer-v4/determinex-observer-v4.gguf
SEN=/workspace/outputs/determinex-sentinel-v3/determinex-sentinel-v3.gguf

all_ok=1
for MODEL_PATH in "$ENG" "$OBS" "$SEN"; do
    NAME=$(basename "$MODEL_PATH")
    if [ ! -f "$MODEL_PATH" ]; then
        echo "  [FAIL] Missing: $MODEL_PATH"
        all_ok=0
        continue
    fi
    SIZE=$(stat -c%s "$MODEL_PATH")
    SIZE_GB=$(echo "scale=2; $SIZE/1000000000" | bc)
    MAGIC=$(python3 -c "f=open('$MODEL_PATH','rb'); print(f.read(4))" 2>/dev/null)
    if [[ "$MAGIC" == "b'GGUF'" ]]; then
        echo "  [PASS] $NAME  ${SIZE_GB} GB  GGUF header OK"
    else
        echo "  [FAIL] $NAME  magic=${MAGIC}  CORRUPT"
        all_ok=0
    fi
done

echo ""
echo "============================================================"
if [ $all_ok -eq 1 ]; then
    echo "  ALL DONE — $(date)"
    echo "  All 3 GGUFs verified. Safe to download:"
    echo ""
    echo "  # Download to VERSIONED brain bank paths (not overwriting):"
    echo "  scp -P <PORT> -i ~/.ssh/id_runpod \\"
    echo "    root@<POD_IP>:$ENG \\"
    echo "    '${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions/engineer/v10/determinex-engineer.gguf'"
    echo ""
    echo "  scp -P <PORT> -i ~/.ssh/id_runpod \\"
    echo "    root@<POD_IP>:$OBS \\"
    echo "    '${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions/observer/v5/determinex-observer.gguf'"
    echo ""
    echo "  scp -P <PORT> -i ~/.ssh/id_runpod \\"
    echo "    root@<POD_IP>:$SEN \\"
    echo "    '${DETERMINEX_MODELS_DIR:-~/determinex-models}/versions/sentinel/v4/determinex-sentinel.gguf'"
else
    echo "  VERIFICATION FAILED — do not download. Check log above."
fi
echo "============================================================"
