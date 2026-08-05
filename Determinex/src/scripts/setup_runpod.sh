#!/usr/bin/env bash
# scripts/setup_runpod.sh — Full Determinex SWE-bench pod setup
# =============================================================
# Run once after the pod boots. Takes ~20 minutes (model download dominates).
#
# Prerequisites (set before running):
#   export DETERMINEX_REPO="https://github.com/YOUR_USERNAME/Determinex.git"
#   export DEEPSEEK_API_KEY="sk-..."
#
# Hardware: RTX 4090 (24 GB) or RTX 3090 (24 GB) recommended.
#   vLLM + Qwen2.5-7B needs ~16 GB VRAM at bfloat16.
#   With 24 GB you also have headroom for the 3B Ollama model alongside.
#
# Cost estimate at $0.44/hr:
#   Setup:  ~0.5 hr  = $0.22
#   Run A:  ~12 hr   = $5.28  (all-7B local, sequential)
#   Run B:  ~6  hr   = $2.64  (all-DeepSeek, fast API)
#   Run C:  ~10 hr   = $4.40  (hybrid, vLLM builder)
#   Total:  ~29 hr   = ~$12.50 pod + ~$8 DeepSeek API = ~$20.50

set -euo pipefail

WORKSPACE="/workspace"
DETERMINEX_DIR="$WORKSPACE/determinex"
REPOS_DIR="$WORKSPACE/swebench-repos"
MODELS_DIR="$WORKSPACE/models"
LOG_DIR="$WORKSPACE/ablation-logs"

echo "================================================================"
echo " Determinex RunPod Setup"
echo " Workspace : $WORKSPACE"
echo " Determinex   : $DETERMINEX_DIR"
echo " Repos     : $REPOS_DIR  (shared across all 3 config runs)"
echo "================================================================"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -q git curl wget build-essential python3-pip tmux htop

# ── 2. Clone Determinex ──────────────────────────────────────────────────────────
echo "[2/7] Cloning Determinex..."
if [ -z "${DETERMINEX_REPO:-}" ]; then
    echo "ERROR: Set DETERMINEX_REPO to your GitHub URL before running setup."
    echo "  export DETERMINEX_REPO=https://github.com/YOUR_USERNAME/Determinex.git"
    exit 1
fi
if [ ! -d "$DETERMINEX_DIR/.git" ]; then
    git clone "$DETERMINEX_REPO" "$DETERMINEX_DIR"
else
    echo "  Already cloned — pulling latest..."
    git -C "$DETERMINEX_DIR" pull
fi

# ── 3. Python dependencies ────────────────────────────────────────────────────
echo "[3/7] Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q \
    datasets \
    swebench \
    huggingface_hub \
    vllm \
    torch \
    numpy \
    fastembed \
    nomic

# ── 4. Install Ollama (Config A — all-local 7B) ───────────────────────────────
echo "[4/7] Installing Ollama..."
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.ai/install.sh | sh
fi

# Start Ollama in background
ollama serve > "$WORKSPACE/ollama.log" 2>&1 &
OLLAMA_PID=$!
echo "  Ollama PID: $OLLAMA_PID (log: $WORKSPACE/ollama.log)"
sleep 8  # wait for Ollama to be ready

# Pull the models needed for Config A
echo "  Pulling qwen2.5-coder:7b-instruct..."
ollama pull qwen2.5-coder:7b-instruct
echo "  Pulling qwen2.5-coder:3b-instruct..."
ollama pull qwen2.5-coder:3b-instruct

# ── 5. Download Qwen2.5-7B for vLLM (Configs B + C) ─────────────────────────
echo "[5/7] Downloading Qwen2.5-Coder-7B-Instruct for vLLM..."
mkdir -p "$MODELS_DIR/qwen7b"
python3 - <<'PYEOF'
import os
from huggingface_hub import snapshot_download
snapshot_download(
    "Qwen/Qwen2.5-Coder-7B-Instruct",
    local_dir=os.environ.get("MODELS_DIR", "/workspace/models") + "/qwen7b",
    ignore_patterns=["*.msgpack", "*.h5", "flax_model*", "tf_model*"],
)
print("  Download complete.")
PYEOF

# ── 6. Start vLLM server ──────────────────────────────────────────────────────
echo "[6/7] Starting vLLM server on port 8000..."
nohup python3 -m vllm.entrypoints.openai.api_server \
    --model "$MODELS_DIR/qwen7b" \
    --port 8000 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.75 \
    --dtype bfloat16 \
    --trust-remote-code \
    > "$WORKSPACE/vllm.log" 2>&1 &
VLLM_PID=$!
echo "  vLLM PID: $VLLM_PID (log: $WORKSPACE/vllm.log)"
echo "  Waiting 60s for model to load into VRAM..."
sleep 60

# Smoke-test vLLM
if curl -s http://localhost:8000/health | grep -q "OK\|{}"; then
    echo "  vLLM healthy."
else
    echo "  WARNING: vLLM health check inconclusive — check $WORKSPACE/vllm.log"
fi

# ── 7. Create shared repos dir ────────────────────────────────────────────────
echo "[7/7] Creating shared repos directory..."
mkdir -p "$REPOS_DIR"
mkdir -p "$LOG_DIR"

# ── Done ──────────────────────────────────────────────────────────────────────
cat <<EOF

================================================================
 Setup complete. Services running:
   Ollama : PID $OLLAMA_PID  — http://localhost:11434
   vLLM   : PID $VLLM_PID   — http://localhost:8000/v1
   Logs   : $WORKSPACE/ollama.log  |  $WORKSPACE/vllm.log

 Next step:
   export DEEPSEEK_API_KEY="sk-..."
   bash $DETERMINEX_DIR/scripts/testing/run_ablation.sh

 Or run a single config smoke test first (3 instances):
   cd $DETERMINEX_DIR
   DEEPSEEK_API_KEY=sk-... python scripts/determinex_swebench_run.py \\
     --split lite --instances 3 --skip-eval \\
     --repos-dir $REPOS_DIR --config b
================================================================
EOF
