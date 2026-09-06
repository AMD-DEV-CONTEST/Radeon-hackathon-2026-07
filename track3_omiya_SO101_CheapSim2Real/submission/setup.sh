#!/usr/bin/env bash
# One-shot setup on a fresh Radeon Cloud instance.
#
# Assumes the AMD ROCm PyTorch template (torch is already installed and sees the GPU).
# Installs everything else this project needs and verifies the machine can run the whole
# pipeline — simulation included — before you spend GPU hours on it.
#
#   bash setup.sh
#
set -euo pipefail

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

cd "$(dirname "$0")"

log "1/5  System libraries (Genesis renders offscreen; ffmpeg decodes dataset video)"
# A "Failed to fetch ... compute-artifactory.amd.com" warning here is harmless: that repo is
# unreachable on some images, and every package below comes from archive.ubuntu.com.
if command -v apt-get >/dev/null; then
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  $SUDO apt-get update -qq || true
  $SUDO apt-get install -y -qq --no-install-recommends \
      ffmpeg libgl1 libglib2.0-0 libosmesa6 libegl1 git
fi

log "2/5  Confirming this Python's torch sees the Radeon GPU"
echo "    python: $(command -v python) ($(python -V 2>&1))"
if ! python -c "import torch" 2>/dev/null; then
  echo
  echo "ABORT: this Python has no torch."
  echo
  # The amd-oneclick-base image keeps its ROCm torch in a virtualenv at /opt/venv, which the
  # template activates by default. Leaving that venv (e.g. `deactivate`) exposes
  # /usr/bin/python, which has no torch — point the user straight back at it.
  if [ -x /opt/venv/bin/python ] && /opt/venv/bin/python -c "import torch" 2>/dev/null; then
    echo "  Found the ROCm torch in /opt/venv. Activate it and re-run:"
    echo
    echo "    source /opt/venv/bin/activate"
    echo "    bash setup.sh"
  else
    echo "  Activate the environment that provides the ROCm build of torch and re-run this"
    echo "  script. On the amd-oneclick-base image that is: source /opt/venv/bin/activate"
  fi
  echo
  echo "  Do NOT 'pip install torch' — the PyPI wheel is the CUDA build and cannot see a"
  echo "  Radeon GPU. This project never installs torch for that reason."
  exit 1
fi
python - <<'PY'
import sys, torch
print("    torch:", torch.__version__)
ok = torch.cuda.is_available()
print("    GPU  :", torch.cuda.get_device_name(0) if ok else "NOT VISIBLE")
if not ok:
    sys.exit("\nABORT: torch is installed but cannot see a GPU. On a ROCm host check that the\n"
             "container was started with --device=/dev/kfd --device=/dev/dri --group-add video,\n"
             "and that this torch is the ROCm build (a '+rocm' suffix in the version above).")
PY

log "3/5  Python dependencies"
# torch is deliberately absent from requirements.txt — see the file's comments.
# torchcodec is never installed: its compiled extension is ABI-incompatible with AMD's
# custom torch build, so every command here passes --dataset.video_backend=pyav.
pip install --quiet --no-cache-dir -r requirements.txt
pip uninstall -y -q torchcodec 2>/dev/null || true

# Compiled-extension ABI check. `import genesis` pulls in scikit-image (built against the
# numpy 2.4 C API) and numba (older releases cap numpy at 2.2), so a base image with a stale
# numba leaves pip resolving to a combination where one of them fails at import — either
# "numpy.dtype size changed ... Expected 96, got 88" or "Numba needs NumPy 2.2 or less".
# Verify the real thing rather than a proxy, and force the verified trio if it fails.
if ! python -c "import genesis" 2>/dev/null; then
  echo "    'import genesis' failed — reinstalling numpy and scikit-image as a matched pair"
  # They must move together: scikit-image's wheels are compiled against one numpy C API, so
  # changing numpy alone swaps one import error for the other.
  pip install --quiet --no-cache-dir --force-reinstall \
      "numpy>=2.2,<2.3" "scikit-image>=0.25,<0.26"
  python -c "import genesis" || {
    echo
    echo "ABORT: 'import genesis' still fails. Show the traceback with:"
    echo "         python -c 'import genesis'"
    echo "  Consumers to satisfy simultaneously: lerobot needs numpy<2.3, scikit-image's"
    echo "  wheels must match the installed numpy's C API, and older numba caps numpy at 2.2."
    exit 1
  }
fi
python -c "import numpy, skimage; print(f'    numpy {numpy.__version__} | scikit-image {skimage.__version__}')"

# Same idea for the LeRobot side. lerobot imports transformers, which in its 4.x line demands
# huggingface-hub<1.0 while lerobot itself needs >=1.0 — a base image carrying transformers 4.x
# therefore fails at `import lerobot.datasets`, several frames deep. transformers 5.x resolves it.
if ! python -c "from lerobot.datasets.lerobot_dataset import LeRobotDataset" 2>/dev/null; then
  echo "    'import lerobot.datasets' failed — upgrading transformers (4.x pins huggingface-hub<1.0)"
  pip install --quiet --no-cache-dir -U "transformers>=5.5" "huggingface-hub>=1.0,<2.0"
  python -c "from lerobot.datasets.lerobot_dataset import LeRobotDataset" || {
    echo
    echo "ABORT: 'import lerobot.datasets' still fails. Show the traceback with:"
    echo "         python -c 'from lerobot.datasets.lerobot_dataset import LeRobotDataset'"
    exit 1
  }
fi
python -c "import importlib.metadata as m; print(f\"    lerobot {m.version('lerobot')} | transformers {m.version('transformers')} | huggingface-hub {m.version('huggingface-hub')}\")"

log "4/5  Environment defaults"
# Genesis rasterises the two cameras through pyrender, whose default pyglet backend needs a
# display and dies headless with "IndexError: list index out of range". EGL renders without
# one. Persist it so later shells inherit it.
ENVLINE='export PYOPENGL_PLATFORM=egl'
grep -qxF "$ENVLINE" ~/.bashrc 2>/dev/null || echo "$ENVLINE" >> ~/.bashrc
export PYOPENGL_PLATFORM=egl
echo "PYOPENGL_PLATFORM=$PYOPENGL_PLATFORM (also appended to ~/.bashrc)"

log "5/5  Smoke test — torch+ROCm, EGL, scene build, both cameras rendering"
python src/smoke_test_rocm.py

log "Setup complete. Next: bash run_pipeline.sh --quick"
