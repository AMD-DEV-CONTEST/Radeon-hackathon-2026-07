#!/usr/bin/env bash
# MeshSmith setup for a Radeon Cloud instance (run inside a rocm/pytorch container).
# Usage: bash scripts/radeon_cloud_setup.sh   (from the repo root)
#
# Instance settings recommended by AMD staff in #devmaster-faq:
#   Image   : GH-proxy-stable   (works out of the box)
#   Storage : Persistent (PVC)  (survives instance destruction)
#   SSH     : enable the toggle before launching if you want shell access
# Note: platform stress tests kill all running instances without warning beyond a
# channel heads-up — don't leave a long unattended run going.
set -euo pipefail

echo "== GPU =="
rocm-smi || true
python -c "import torch; print('torch', torch.__version__, '| hip', torch.version.hip, '| device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE')"

echo "== System libs (opencv, a Hunyuan3D dep, needs OpenGL/glib) =="
if ! python -c "import ctypes; ctypes.CDLL('libGL.so.1')" 2>/dev/null; then
  (apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0) \
    || sudo apt-get install -y --no-install-recommends libgl1 libglib2.0-0
fi

echo "== Checking the container's torch stack =="
python -c "import torch, torchvision; print('torch', torch.__version__, '| torchvision', torchvision.__version__, '| hip', torch.version.hip)"

echo "== Installing MeshSmith deps (torch + torchvision come from the container) =="
pip install --no-cache-dir -r requirements.txt
python -c "import torch; assert torch.version.hip, 'ROCm torch was replaced by a non-ROCm build!'; print('ROCm torch intact')"

echo "== Smoke test (model-free) =="
python scripts/smoke_test.py

echo "== Warm the model caches with one draft asset =="
python -m meshsmith.cli "a chess knight piece" --quality draft --seed 7

echo
echo "Done. Start the UI with:"
echo "  python app.py --host 0.0.0.0 --port 7860"
echo "Expose it publicly from a Radeon Cloud notebook with:"
echo "  \"\$HOME/.local/bin/rc-tunnel\" expose --port 7860"
