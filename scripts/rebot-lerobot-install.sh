#!/usr/bin/env bash
# One-shot install: Seeed LeRobot + B601-RS robot plugin + Star Arm 102 leader teleop.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LROOT="${REBOT_LEROBOT_ROOT:-$HOME/rebot_lerobot}"
VENV="${REBOT_LEROBOT_VENV:-$HOME/venvs/lerobot}"
PY="${PYTHON:-python3.12}"

echo "[rebot-lerobot] clone Seeed-Projects/lerobot ..."
mkdir -p "$LROOT"
if [[ ! -d "$LROOT/lerobot/.git" ]]; then
  git clone --depth 1 https://github.com/Seeed-Projects/lerobot.git "$LROOT/lerobot"
fi

echo "[rebot-lerobot] create venv at $VENV ..."
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip wheel setuptools

echo "[rebot-lerobot] install lerobot (editable) — this downloads torch, may take 10–20 min ..."
pip install -e "$LROOT/lerobot"

echo "[rebot-lerobot] install B601-RS + leader plugins ..."
pip install lerobot-teleoperator-rebot-arm-102 lerobot-robot-seeed-b601 motorbridge

echo "[rebot-lerobot] install ffmpeg for dataset video encoding ..."
pip install av 2>/dev/null || true
if command -v ffmpeg >/dev/null 2>&1; then
  echo "  system ffmpeg: $(ffmpeg -version | head -1)"
else
  echo "  WARNING: ffmpeg not found — install with: sudo apt install ffmpeg"
fi

echo
echo "[rebot-lerobot] verify ..."
python -c "import torch; print('  torch', torch.__version__, 'cuda', torch.cuda.is_available())"
lerobot-calibrate --help >/dev/null && echo "  lerobot-calibrate OK"
lerobot-teleoperate --help >/dev/null && echo "  lerobot-teleoperate OK"
lerobot-record --help >/dev/null && echo "  lerobot-record OK"

for arg in "$@"; do
  case "$arg" in
    --with-pinocchio)
      echo "[rebot-lerobot] optional: Pinocchio SDK ..."
      bash "$ROOT/scripts/b601_pinocchio_install.sh"
      ;;
    --with-ros2)
      echo "[rebot-lerobot] optional: ROS2 workspace ..."
      bash "$ROOT/scripts/b601_ros2_install.sh"
      ;;
  esac
done
echo
echo "Done. Next:"
echo "  1. Plug Star Arm 102 leader USB → should appear as /dev/ttyUSB0"
echo "  2. bash $ROOT/scripts/rebot-setup-can.sh"
echo "  3. bash $ROOT/scripts/rebot-lerobot-calibrate.sh"
echo "  4. bash $ROOT/scripts/rebot-teleop.sh"
