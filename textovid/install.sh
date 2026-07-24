#!/usr/bin/env bash
# Textovid — Installation script for AMD ROCm 7.2 instance
set -euo pipefail

VENV="/opt/venv"
WORKSPACE="/workspace/textovid"

echo "========================================"
echo "  Textovid Install Script"
echo "  ROCm 7.2 / RX 7900 XTX"
echo "========================================"

# ── 1. System packages ──────────────────────────────────────────
echo "[1/5] Installing system packages …"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3.11-venv python3-pip git wget \
    libgl1 libglib2.0-0 \
    ffmpeg 2>&1 | tail -3

# ── 2. Python venv (use pre-existing /opt/venv if present) ──────
echo "[2/5] Setting up Python venv at $VENV …"
if [ ! -d "$VENV" ]; then
    sudo python3.11 -m venv "$VENV"
    sudo chown -R $(whoami):$(whoami) "$VENV"
fi
source "$VENV/bin/activate"

# ── 3. PyTorch (ROCm 7.2) ───────────────────────────────────────
echo "[3/5] Installing PyTorch for ROCm 7.2 …"
pip install --upgrade pip setuptools wheel -q
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.2 -q
python -c "import torch; print(f'PyTorch {torch.__version__}, CUDA available: {torch.cuda.is_available()}')"

# ── 4. Python dependencies ──────────────────────────────────────
echo "[4/5] Installing Python dependencies …"
cd "$WORKSPACE"
pip install -r requirements.txt -q 2>&1 | tail -5

# ── 5. Download frpc binary for Gradio share links ──────────────
echo "[5/5] Downloading frpc binary for Gradio share …"
FRPC_DIR="$HOME/.cache/huggingface/gradio/frpc"
mkdir -p "$FRPC_DIR"
if [ ! -f "$FRPC_DIR/frpc_linux_amd64_v0.3" ]; then
    wget -q -O "$FRPC_DIR/frpc_linux_amd64_v0.3" \
        https://github.com/gradio-app/frpc/releases/download/v0.3/linux-amd64
    chmod +x "$FRPC_DIR/frpc_linux_amd64_v0.3"
fi
echo "frpc binary ready."

echo ""
echo "========================================"
echo "  Installation complete!"
echo "  Run:  cd $WORKSPACE && python app.py"
echo "========================================"
