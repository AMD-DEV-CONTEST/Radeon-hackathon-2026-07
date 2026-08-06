#!/usr/bin/env bash
# Recover B601-RS follower after fault / teleop exit / gateway conflict.
# Clears errors and re-enables all 7 RobStride motors on can0.
# Does NOT start motorbridge-gateway — safe before lerobot-teleoperate.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAN="${FOLLOWER_CAN:-can0}"

# shellcheck disable=SC1091
source "${REBOT_LEROBOT_VENV:-$HOME/venvs/lerobot}/bin/activate" 2>/dev/null \
  || source "${REBOT_VENV:-$HOME/venvs/rebot}/bin/activate"

pkill -f motorbridge-gateway 2>/dev/null || true
sleep 0.5

echo "[recover] bringing up $CAN ..."
bash "$ROOT/scripts/rebot-setup-can.sh" "$CAN" || true

echo "[recover] scanning motors 1-7 ..."
motorbridge-cli scan \
  --vendor robstride --channel "$CAN" --transport socketcan \
  --start-id 1 --end-id 7 --feedback-ids 0xFD --timeout-ms 500 \
  | tail -5

enable_one() {
  local id=$1 model=$2
  echo "[recover] motor 0x$id: clear-error + enable ($model) ..."
  motorbridge-cli run --vendor robstride --channel "$CAN" --transport socketcan \
    --motor-id "$id" --feedback-id 0xFD --model "$model" \
    --mode clear-error --timeout-ms 800 2>/dev/null || true
  motorbridge-cli run --vendor robstride --channel "$CAN" --transport socketcan \
    --motor-id "$id" --feedback-id 0xFD --model "$model" \
    --mode enable --timeout-ms 800 2>/dev/null || true
}

# J1-J3 rs-06, J4-J7 rs-00 (matches lerobot_robot_seeed_b601)
for id in 1 2 3; do enable_one "$id" rs-06; done
for id in 4 5 6 7; do enable_one "$id" rs-00; done

echo
echo "[recover] done. Motors should hold position briefly."
echo "  NOW run (within ~10s, before auto-disable):"
echo "    bash $ROOT/scripts/rebot-teleop.sh"
echo
echo "  If arm still limp DURING teleop, power-cycle 48V and repeat."
