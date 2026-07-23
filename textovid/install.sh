#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  TEXTOVID — Quick Install Script
#  Run in JupyterLab terminal on your AMD Radeon GPU instance
# ═══════════════════════════════════════════════════════════════

set -e
echo ""
echo "========================================================"
echo "  TEXTOVID — AI Comic Studio — Quick Install"
echo "  AMD AI DevMaster Hackathon 2026"
echo "========================================================"
echo ""

# ── Step 1: Install PyTorch ROCm ──────────────────────────────
echo "[1/3] Installing PyTorch with ROCm support..."
echo "  (This takes 2-5 minutes, one-time only)"

# Try ROCm 6.2 first, then fallbacks
for ROCM_URL in \
    "https://download.pytorch.org/whl/rocm6.2" \
    "https://download.pytorch.org/whl/rocm6.1" \
    "https://download.pytorch.org/whl/rocm6.0"; do
    echo "  Trying: $ROCM_URL"
    if pip install torch torchvision torchaudio --index-url "$ROCM_URL" -q 2>/dev/null; then
        echo "  ✓ PyTorch ROCm installed!"
        break
    else
        echo "  ✗ Not found, trying next..."
    fi
done

# ── Step 2: Install dependencies ──────────────────────────────
echo ""
echo "[2/3] Installing Python dependencies..."

pip install -q \
    diffusers>=0.30.0 \
    transformers>=4.42.0 \
    accelerate>=0.33.0 \
    "gradio>=4.40.0" \
    Pillow>=10.0.0 \
    requests>=2.31.0 \
    safetensors>=0.4.0 \
    imageio>=2.34.0 \
    imageio-ffmpeg>=0.5.1

echo "  ✓ All dependencies installed"

# ── Step 3: Verify ────────────────────────────────────────────
echo ""
echo "[3/3] Verifying installation..."
echo "  ----------------------------------------------------"

python3 -c "
import torch
print(f'  PyTorch:    {torch.__version__}')
print(f'  CUDA/HIP:   {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU:        {torch.cuda.get_device_name(0)}')
    try:
        p = torch.cuda.get_device_properties(0)
        print(f'  VRAM:       {round(p.total_mem/1e9, 2)} GB')
    except: pass
    try:
        print(f'  ROCm:       {torch.version.hip}')
    except: pass
else:
    print('  ⚠ No GPU detected!')
import diffusers; print(f'  Diffusers:  {diffusers.__version__}')
import gradio;   print(f'  Gradio:     {gradio.__version__}')
print('  ----------------------------------------------------')
"

echo ""
echo "========================================================"
echo "  ✅ INSTALL COMPLETE!"
echo "========================================================"
echo ""
echo "  NOW DO THIS:"
echo "  1. Get your FREE API key:"
echo "     → https://developer.amd.com.cn/radeon/modelapis"
echo "     → Click 'Token Factory' → Generate Key"
echo ""
echo "  2. Upload the textovid/ folder to /workspace/"
echo ""
echo "  3. Run:  cd /workspace/textovid && python app.py"
echo ""
echo "  4. Open the URL (usually http://0.0.0.0:7860)"
echo "  5. Paste your API key and generate!"
echo ""