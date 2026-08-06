#!/usr/bin/env bash
# Calibrate B601-RS follower + Star Arm 102 leader (interactive).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/rebot-lerobot-env.sh"

LEADER_PORT="${LEADER_PORT:-/dev/ttyUSB0}"
FOLLOWER_CAN="${FOLLOWER_CAN:-can0}"
ROBOT_ID="${ROBOT_ID:-follower1}"
LEADER_ID="${LEADER_ID:-rebot_arm_102_leader}"

if [[ ! -e "$LEADER_PORT" ]]; then
  echo "[calibrate] ERROR: leader port $LEADER_PORT not found."
  echo "  Plug Star Arm 102 USB, then: ls /dev/ttyUSB*"
  echo "  If brltty steals the port: sudo apt remove brltty"
  exit 1
fi

echo "[calibrate] CAN $FOLLOWER_CAN ..."
bash "$ROOT/scripts/rebot-setup-can.sh" "$FOLLOWER_CAN"

echo
echo "=== Follower (B601-RS) — move to zero pose (gripper closed), press ENTER ==="
lerobot-calibrate \
  --robot.type=seeed_b601_rs_follower \
  --robot.port="$FOLLOWER_CAN" \
  --robot.id="$ROBOT_ID" \
  --robot.can_adapter=socketcan

echo
echo "=== Leader (Star Arm 102) — move to zero pose, keep still, press ENTER ==="
sudo chmod 666 "$LEADER_PORT" 2>/dev/null || true
lerobot-calibrate \
  --teleop.type=rebot_arm_102_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID"

echo
echo "[calibrate] test leader raw angles:"
python "$HOME/rebot_lerobot/lerobot/../" 2>/dev/null || true
if python -c "import lerobot_teleoperator_rebot_arm_102" 2>/dev/null; then
  PKG=$(python -c "import lerobot_teleoperator_rebot_arm_102, pathlib; print(pathlib.Path(lerobot_teleoperator_rebot_arm_102.__file__).parent)")
  if [[ -f "$PKG/../examples/read_raw_angles.py" ]]; then
    python "$PKG/../examples/read_raw_angles.py" --port "$LEADER_PORT" || true
  fi
fi
echo "[calibrate] done. Calibration stored under ~/.cache/huggingface/lerobot/calibration/"
