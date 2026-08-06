#!/usr/bin/env bash
# Record first imitation-learning dataset: leader teleop + follower + cameras.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/scripts/rebot-lerobot-env.sh"

LEADER_PORT="${LEADER_PORT:-/dev/ttyUSB0}"
FOLLOWER_CAN="${FOLLOWER_CAN:-can0}"
ROBOT_ID="${ROBOT_ID:-follower1}"
LEADER_ID="${LEADER_ID:-rebot_arm_102_leader}"
DATASET_REPO="${DATASET_REPO:-local/rebot_b601_rs/demo01}"
NUM_EPISODES="${NUM_EPISODES:-5}"
TASK="${TASK:-Pick and place the object}"
EPISODE_TIME="${EPISODE_TIME:-30}"
RESET_TIME="${RESET_TIME:-30}"
PUSH_HUB="${PUSH_HUB:-false}"
CAMERAS="${REBOT_CAMERAS:-{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30, fourcc: \"MJPG\"}, side: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30, fourcc: \"MJPG\"} }}"

if [[ ! -e "$LEADER_PORT" ]]; then
  echo "[record] ERROR: leader $LEADER_PORT not found"
  exit 1
fi

bash "$ROOT/scripts/rebot-setup-can.sh" "$FOLLOWER_CAN" 2>/dev/null || true
sudo chmod 666 "$LEADER_PORT" 2>/dev/null || true

echo "[record] dataset: $DATASET_REPO"
echo "[record] episodes: $NUM_EPISODES × ${EPISODE_TIME}s  task: $TASK"
echo "[record] saved under ~/.cache/huggingface/lerobot/$DATASET_REPO"
echo "[record] find cameras first: lerobot-find-cameras opencv"

exec lerobot-record \
  --robot.type=seeed_b601_rs_follower \
  --robot.port="$FOLLOWER_CAN" \
  --robot.id="$ROBOT_ID" \
  --robot.can_adapter=socketcan \
  --robot.cameras="$CAMERAS" \
  --teleop.type=rebot_arm_102_leader \
  --teleop.port="$LEADER_PORT" \
  --teleop.id="$LEADER_ID" \
  --display_data=true \
  --dataset.repo_id="$DATASET_REPO" \
  --dataset.num_episodes="$NUM_EPISODES" \
  --dataset.single_task="$TASK" \
  --dataset.push_to_hub="$PUSH_HUB" \
  --dataset.episode_time_s="$EPISODE_TIME" \
  --dataset.reset_time_s="$RESET_TIME"
