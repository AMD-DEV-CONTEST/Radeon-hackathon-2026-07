#!/usr/bin/env bash
# watch_sentinel.sh — polls RunPod for Sentinel GGUF, pulls it, registers it, evals it
# Run from Git Bash: bash scripts/watch_sentinel.sh
set -euo pipefail

POD_USER="dfafcvn56sa42n-64411461"
POD_HOST="ssh.runpod.io"
SSH_KEY="$HOME/.ssh/id_runpod"
MODEL_NAME="determinex-7-large-v1.1"
LOCAL_GGUF="$HOME/.determinex/models/${MODEL_NAME}.gguf"
DETERMINEX="$(cd "$(dirname "$0")/.." && pwd)"
POLL_INTERVAL=60

SSH_CMD="ssh -t -o StrictHostKeyChecking=no -o ConnectTimeout=20 -i $SSH_KEY ${POD_USER}@${POD_HOST}"
SCP_CMD="scp -o StrictHostKeyChecking=no -o ConnectTimeout=30 -i $SSH_KEY"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Watching for ${MODEL_NAME} GGUF on RunPod..."
log "Will save to: $LOCAL_GGUF"
log "Polling every ${POLL_INTERVAL}s — Ctrl+C to abort"
echo ""

mkdir -p "$HOME/.determinex/models"

while true; do
    # Check if GGUF exists on pod
    GGUF_PATH=$($SSH_CMD "ls /workspace/output/${MODEL_NAME}.gguf 2>/dev/null || echo ''" 2>/dev/null | tr -d '\r' | grep -v '^$' | tail -1 || true)

    if [[ -n "$GGUF_PATH" && "$GGUF_PATH" == *".gguf"* ]]; then
        log "GGUF found: $GGUF_PATH"
        log "Checking size..."
        GGUF_SIZE=$($SSH_CMD "stat -c%s /workspace/output/${MODEL_NAME}.gguf 2>/dev/null || echo 0" 2>/dev/null | tr -d '\r' | tail -1 || echo 0)
        log "Size: ${GGUF_SIZE} bytes"

        if [[ "$GGUF_SIZE" -lt 1000000000 ]]; then
            log "File too small (${GGUF_SIZE} bytes) — conversion still in progress, waiting..."
        else
            log "Size OK — pulling down..."
            $SCP_CMD "${POD_USER}@${POD_HOST}:/workspace/output/${MODEL_NAME}.gguf" "$LOCAL_GGUF"
            log "Download complete: $LOCAL_GGUF"
            break
        fi
    else
        # Show what's running on pod
        STATUS=$($SSH_CMD "ps aux | grep -E 'convert|python|llama' | grep -v grep | head -3 2>/dev/null || echo 'checking...'" 2>/dev/null | tr -d '\r' || true)
        log "Not ready yet. Pod status: ${STATUS:-idle/converting}"
    fi

    sleep $POLL_INTERVAL
done

# ── Register with Ollama ──────────────────────────────────────────────────────
log "Registering ${MODEL_NAME} with Ollama..."

MODELFILE_PATH="$DETERMINEX/scripts/fine_tuning/${MODEL_NAME}.Modelfile"
cat > "$MODELFILE_PATH" <<EOF
FROM $LOCAL_GGUF

PARAMETER stop "<|im_end|>"
PARAMETER stop "<|fim_middle|>"
PARAMETER stop "<|fim_prefix|>"
PARAMETER stop "<|fim_suffix|>"
PARAMETER num_ctx 16384
PARAMETER temperature 0.1

SYSTEM "You are Determinex Sentinel, an expert code generation assistant specializing in Rust, Go, Python, and TypeScript. Generate precise, compiler-verified code. Return only code without explanation unless asked."
EOF

ollama create "${MODEL_NAME}" -f "$MODELFILE_PATH"
log "Registered ${MODEL_NAME} in Ollama"

# ── micro_eval ────────────────────────────────────────────────────────────────
log "Running micro_eval (45 probes, compiler-verified)..."
cd "$DETERMINEX"
python scripts/micro_eval.py --model "${MODEL_NAME}" --save-micro-eval --compare 2>&1 | tee /tmp/sentinel_micro_eval.txt

# ── Full benchmark scorecard ──────────────────────────────────────────────────
log "Running full benchmark scorecard..."
python scripts/determinex_benchmark.py --eval-model "${MODEL_NAME}" 2>&1 | tee /tmp/sentinel_benchmark.txt

# ── 3-model scorecard summary ────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  DETERMINEX v1.1 — FULL 3-MODEL SCORECARD"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  micro_eval results (compiler-verified, 45 probes each):"
echo ""

for model in determinex-1-tiny-v1.1 determinex-3-medium-v1.1 determinex-7-large-v1.1; do
    EVAL_FILE="$DETERMINEX/scripts/fine_tuning/eval_results/${model}_micro_eval.json"
    if [[ -f "$EVAL_FILE" ]]; then
        SCORE=$(python -c "import json; d=json.load(open('$EVAL_FILE')); print(f\"{d['compile_rate']*100:.1f}%\")" 2>/dev/null || echo "N/A")
        printf "  %-32s  %s\n" "$model" "$SCORE"
    else
        printf "  %-32s  not yet evaluated\n" "$model"
    fi
done

echo ""
echo "  Full scorecard saved to /tmp/sentinel_benchmark.txt"
echo "════════════════════════════════════════════════════════════════"
