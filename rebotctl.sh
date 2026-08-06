#!/usr/bin/env bash
# B601-RS control — run from ANY directory.
# Usage:
#   bash /home/amd/下载/dev/botversex/rebotctl.sh teleop
#   bash /home/amd/下载/dev/botversex/rebotctl.sh recover
#   bash /home/amd/下载/dev/botversex/rebotctl.sh can
#   bash /home/amd/下载/dev/botversex/rebotctl.sh record
set -euo pipefail

BOTVERSEX="/home/amd/下载/dev/botversex"
SCRIPTS="$BOTVERSEX/scripts"

cmd="${1:-help}"
shift || true

case "$cmd" in
  can|setup-can)
    exec bash "$SCRIPTS/rebot-setup-can.sh" "$@"
    ;;
  recover|fix)
    pkill -f motorbridge-gateway 2>/dev/null || true
    exec bash "$SCRIPTS/rebot-recover-follower.sh" "$@"
    ;;
  disable|off|release)
    exec bash "$SCRIPTS/rebot-disable-follower.sh" "$@"
    ;;
  teleop|t)
    pkill -f motorbridge-gateway 2>/dev/null || true
    bash "$SCRIPTS/rebot-setup-can.sh" can0 2>/dev/null || true
    exec bash "$SCRIPTS/rebot-teleop.sh" "$@"
    ;;
  record|r)
    pkill -f motorbridge-gateway 2>/dev/null || true
    bash "$SCRIPTS/rebot-setup-can.sh" can0 2>/dev/null || true
    exec bash "$SCRIPTS/rebot-record.sh" "$@"
    ;;
  calibrate|c)
    exec bash "$SCRIPTS/rebot-lerobot-calibrate.sh" "$@"
    ;;
  gateway|studio)
    exec bash "$SCRIPTS/rebot-start-gateway.sh" "$@"
    ;;
  kill-gateway)
    pkill -f motorbridge-gateway 2>/dev/null || true
    echo "motorbridge-gateway stopped"
    ;;
  help|*)
    cat <<EOF
B601-RS 控制（任意目录可运行）

  bash $BOTVERSEX/rebotctl.sh teleop     # 遥操（先关 gateway，再 CAN，再 teleop）
  bash $BOTVERSEX/rebotctl.sh recover    # 从臂 fault 恢复 + enable
  bash $BOTVERSEX/rebotctl.sh can        # 只配置 CAN
  bash $BOTVERSEX/rebotctl.sh record     # 录数据集
  bash $BOTVERSEX/rebotctl.sh calibrate  # 重新校准
  bash $BOTVERSEX/rebotctl.sh gateway    # 开 MotorBridge Studio（调试时用，勿与 teleop 同时）
  bash $BOTVERSEX/rebotctl.sh kill-gateway

推荐遥操流程：
  bash $BOTVERSEX/rebotctl.sh recover
  bash $BOTVERSEX/rebotctl.sh teleop

脚本目录: $SCRIPTS
EOF
    ;;
esac
