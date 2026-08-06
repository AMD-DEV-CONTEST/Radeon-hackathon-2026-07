#!/usr/bin/env bash
# Install reBotArmController_ROS2 workspace for B601 MoveIt2 / bringup bridge.
set -euo pipefail

WS="${REBOTARM_ROS2_WS:-${HOME}/rebotarm_ros2}"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
REPO="${B601_ROS2_REPO:-https://github.com/Seeed-Projects/reBotArmController_ROS2.git}"
SDK_REPO="${B601_SDK_REPO:-https://github.com/vectorBH6/reBotArm_control_py.git}"

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 not found. Install ROS2 ${ROS_DISTRO} first:"
  echo "  https://wiki.seeedstudio.com/cn/rebot_arm_b601_rs_ros2_integration/"
  exit 1
fi

mkdir -p "${WS}"
if [[ ! -d "${WS}/.git" ]]; then
  git clone --depth 1 "${REPO}" "${WS}"
fi

mkdir -p "${WS}/third_party"
if [[ ! -d "${WS}/third_party/reBotArm_control_py/.git" ]]; then
  git clone --depth 1 "${SDK_REPO}" "${WS}/third_party/reBotArm_control_py"
fi

source "/opt/ros/${ROS_DISTRO}/setup.bash"
cd "${WS}"

sudo apt-get update
sudo apt-get install -y python3-colcon-common-extensions python3-pip git || true
sudo apt-get install -y \
  "ros-${ROS_DISTRO}-control-msgs" \
  "ros-${ROS_DISTRO}-trajectory-msgs" \
  "ros-${ROS_DISTRO}-robot-state-publisher" \
  "ros-${ROS_DISTRO}-rviz2" \
  "ros-${ROS_DISTRO}-pinocchio" || true

python3 -m pip install --user --break-system-packages motorbridge 2>/dev/null || \
  python3 -m pip install --user motorbridge

colcon build --symlink-install
echo "source ${WS}/install/setup.bash" >> "${HOME}/.bashrc" || true
echo "[b601-ros2] Done. Restart shell and Local Agent."
