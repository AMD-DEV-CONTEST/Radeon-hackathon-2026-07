#!/usr/bin/env bash
# Activate reBot Python env and start MotorBridge gateway for B601 web UI.
#
# Prerequisite: CAN up — run scripts/rebot-setup-can.sh first (needs sudo).
# Then open https://motorbridge.github.io/motorbridge-studio/ and connect to
# ws://127.0.0.1:9002
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REBOT_VENV:-$HOME/venvs/rebot}"
BIND="${MOTORBRIDGE_BIND:-127.0.0.1:9002}"

if [[ ! -x "$VENV/bin/motorbridge-gateway" ]]; then
  echo "[rebot] motorbridge not found in $VENV"
  echo "        Create env:  python3.12 -m venv ~/venvs/rebot && ~/venvs/rebot/bin/pip install motorbridge"
  echo "        Or conda:    conda activate rebot && pip install motorbridge"
  exit 1
fi

# Warn if CAN is still DOWN (gateway may start but arm won't respond).
if ip link show can0 &>/dev/null; then
  STATE="$(ip -br link show can0 | awk '{print $3}')"
  if [[ "$STATE" != "UP" ]]; then
    echo "[rebot] WARNING: can0 is $STATE — run: bash $ROOT/scripts/rebot-setup-can.sh"
  fi
fi

echo "[rebot] starting motorbridge-gateway on $BIND"
echo "[rebot] studio UI: https://motorbridge.github.io/motorbridge-studio/"
exec "$VENV/bin/motorbridge-gateway" --bind "$BIND"
