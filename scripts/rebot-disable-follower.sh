#!/usr/bin/env bash
# Disable B601-RS follower torque after teleop / record exit.
# Mirrors motorbridge-cli disable (official LeRobot seeed_b601 disconnect path).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAN="${FOLLOWER_CAN:-can0}"

# shellcheck disable=SC1091
source "${REBOT_LEROBOT_VENV:-$HOME/venvs/lerobot}/bin/activate" 2>/dev/null \
  || source "${REBOT_VENV:-$HOME/venvs/rebot}/bin/activate"

pkill -f motorbridge-gateway 2>/dev/null || true

disable_one() {
  local id=$1 model=$2
  echo "[disable] motor 0x$id ($model) ..."
  motorbridge-cli run --vendor robstride --channel "$CAN" --transport socketcan \
    --motor-id "$id" --feedback-id 0xFD --model "$model" \
    --mode disable --timeout-ms 800 2>/dev/null || true
}

for id in 1 2 3; do disable_one "$id" rs-06; done
for id in 4 5 6 7; do disable_one "$id" rs-00; done

echo "[disable] done — follower should be back-drivable (no holding torque)."
