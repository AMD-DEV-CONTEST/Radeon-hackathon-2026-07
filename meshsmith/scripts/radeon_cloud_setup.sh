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
set -uo pipefail

say() { printf '\n== %s ==\n' "$*"; }
die() { printf '\nFATAL: %s\n' "$*" >&2; exit 1; }

# Some images need this to let pip touch the system environment (PEP 668).
PIPFLAGS="--no-cache-dir"
if python -c "import sysconfig,os;raise SystemExit(0 if os.path.exists(os.path.join(sysconfig.get_paths()['stdlib'],'EXTERNALLY-MANAGED')) else 1)" 2>/dev/null; then
  PIPFLAGS="$PIPFLAGS --break-system-packages"
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

say "GPU"
rocm-smi || true
python - <<'PY' || die "torch is not importable — is this a rocm/pytorch image?"
import torch
print("torch", torch.__version__, "| hip", torch.version.hip)
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE VISIBLE")
PY

say "System packages (git for the Hunyuan3D install; libGL/glib for opencv)"
need_apt=""
command -v git >/dev/null 2>&1 || need_apt="$need_apt git"
python -c "import ctypes; ctypes.CDLL('libGL.so.1')" 2>/dev/null || need_apt="$need_apt libgl1 libglib2.0-0"
if [ -n "$need_apt" ]; then
  echo "installing:$need_apt"
  $SUDO apt-get update -qq && $SUDO apt-get install -y --no-install-recommends $need_apt \
    || echo "WARNING: apt install failed; continuing (packages may already be present)"
fi

say "torchvision (Hunyuan3D imports it at load time; NOT installable from PyPI here)"
if ! python -c "import torchvision" 2>/dev/null; then
  # Derive the matching ROCm wheel index from the installed torch, so we never
  # pull a CUDA/CPU wheel that would shadow the container's ROCm torch.
  IDX=$(python - <<'PY'
import torch, re
hip = getattr(torch.version, "hip", None) or ""
m = re.match(r"(\d+)\.(\d+)", hip)
print(f"rocm{m.group(1)}.{m.group(2)}" if m else "")
PY
)
  if [ -n "$IDX" ]; then
    echo "installing torchvision from $IDX"
    pip install $PIPFLAGS torchvision --index-url "https://download.pytorch.org/whl/$IDX" \
      || pip install $PIPFLAGS torchvision --index-url "https://download.pytorch.org/whl/rocm6.4" \
      || die "could not install torchvision — install it manually from the ROCm index"
  else
    die "torchvision missing and ROCm version undetectable; install it manually"
  fi
fi
python -c "import torch, torchvision; print('torch', torch.__version__, '| torchvision', torchvision.__version__, '| hip', torch.version.hip)" \
  || die "torch/torchvision still not importable"

say "Keeping model weights on persistent storage if one is mounted"
# /persistent is where Radeon Cloud mounts the PVC ("Local SSD + /persistent PVC")
for d in /persistent /workspace /data /root/persistent "$HOME"; do
  if [ -d "$d" ] && [ -w "$d" ]; then
    export HF_HOME="$d/.cache/huggingface"
    mkdir -p "$HF_HOME"
    echo "HF_HOME=$HF_HOME"
    grep -q "HF_HOME=$HF_HOME" "$HOME/.bashrc" 2>/dev/null || echo "export HF_HOME=$HF_HOME" >> "$HOME/.bashrc"
    break
  fi
done

say "Installing MeshSmith dependencies (torch + torchvision come from the container)"
pip install $PIPFLAGS -r requirements.txt || die "dependency install failed"
python -c "import torch; assert torch.version.hip, 'ROCm torch was replaced by a non-ROCm build!'; print('ROCm torch intact:', torch.__version__)" \
  || die "the requirements install clobbered the ROCm torch"

say "Smoke test (model-free, no GPU needed)"
python scripts/smoke_test.py || die "smoke test failed"

say "Warming the model caches with one draft asset (downloads ~9GB on first run)"
python -m meshsmith.cli "a chess knight piece, ornate baroque style" --quality draft --seed 7 \
  || die "first generation failed"

cat <<'EOF'

=========================================================
 READY. Next steps:
   Benchmark on Radeon : python scripts/benchmark.py --quality standard --out docs/benchmark.md
   Start the UI        : python app.py --host 0.0.0.0 --port 7860
   Public URL (notebook): "$HOME/.local/bin/rc-tunnel" expose --port 7860
 Destroy the instance when finished — it burns credits while running.
=========================================================
EOF
