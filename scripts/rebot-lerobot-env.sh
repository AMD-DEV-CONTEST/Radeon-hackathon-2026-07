#!/usr/bin/env bash
# Activate the LeRobot venv for B601-RS + Star Arm 102 leader.
# Usage: source scripts/rebot-lerobot-env.sh
export REBOT_LEROBOT_ROOT="${REBOT_LEROBOT_ROOT:-$HOME/rebot_lerobot/lerobot}"
export REBOT_LEROBOT_VENV="${REBOT_LEROBOT_VENV:-$HOME/venvs/lerobot}"
if [[ ! -x "$REBOT_LEROBOT_VENV/bin/python" ]]; then
  echo "[rebot-lerobot] missing venv: $REBOT_LEROBOT_VENV"
  echo "  run: bash scripts/rebot-lerobot-install.sh"
  return 1 2>/dev/null || exit 1
fi
# shellcheck disable=SC1091
source "$REBOT_LEROBOT_VENV/bin/activate"
export PATH="$REBOT_LEROBOT_VENV/bin:$PATH"
