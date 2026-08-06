#!/usr/bin/env bash
# Leader-follower teleoperation: move Star Arm 102 → B601-RS follows.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/rebot-lerobot-env.sh"

LEADER_PORT="${LEADER_PORT:-/dev/ttyUSB0}"
FOLLOWER_CAN="${FOLLOWER_CAN:-can0}"
ROBOT_ID="${ROBOT_ID:-follower1}"
LEADER_ID="${LEADER_ID:-rebot_arm_102_leader}"
# Comma-free camera dict — override with REBOT_CAMERAS env if needed.
CAMERAS="${REBOT_CAMERAS:-{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30, fourcc: \"MJPG\"} }}"
DISPLAY_DATA="${DISPLAY_DATA:-false}"

if [[ ! -e "$LEADER_PORT" ]]; then
  echo "[teleop] ERROR: leader $LEADER_PORT not found — plug Star Arm 102 USB"
  exit 1
fi

bash "$ROOT/scripts/rebot-setup-can.sh" "$FOLLOWER_CAN" 2>/dev/null || true
sudo chmod 666 "$LEADER_PORT" 2>/dev/null || true

echo "[teleop] Leader $LEADER_PORT → Follower $FOLLOWER_CAN"
echo "[teleop] Ctrl+C to stop. Keep ≥1m clearance."
export RERUN=off
exec lerobot-teleoperate \
  --robot.type=seeed_b601_rs_follower \
  --robot.port="$FOLLOWER_CAN" \
  --robot.id="$ROBOT_ID" \
  --robot.can_adapter=socketcan \
  --robot.cameras="$CAMERAS" \
  --teleop.type=rebot_arm_102_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID" \
  --display_data="$DISPLAY_DATA"
