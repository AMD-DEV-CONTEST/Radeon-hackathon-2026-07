#!/usr/bin/env bash
# B601 hardware diagnostic — run in your terminal (needs sudo for CAN once).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAN="${FOLLOWER_CAN:-can0}"
VENV="${REBOT_LEROBOT_VENV:-$HOME/venvs/lerobot}"
CLI="$VENV/bin/motorbridge-cli"
PY="$VENV/bin/python3"
[[ -x "$CLI" ]] || CLI="$(command -v motorbridge-cli)"
[[ -x "$PY" ]] || PY="$(command -v python3)"

echo "=============================================="
echo " B601-RS hardware diagnostic"
echo " $(date '+%F %T')"
echo "=============================================="

echo
echo "[1] Competing processes (should be empty before test):"
pgrep -af 'run_api|lerobot-teleoperate|b601_teleop|motorbridge-gateway' || echo "  (none)"

echo
echo "[2] USB:"
lsusb | grep -iE 'peak|pcan' || echo "  WARNING: PCAN not in lsusb"
ls -la /dev/ttyUSB* 2>/dev/null || echo "  WARNING: no /dev/ttyUSB* (leader)"

echo
echo "[3] CAN interface (before setup):"
ip -br link show "$CAN" 2>/dev/null || echo "  $CAN not found"

echo
echo "[4] Bringing up $CAN (sudo)..."
bash "$ROOT/scripts/rebot-setup-can.sh" "$CAN"

echo
echo "[5] Broadcast scan 1-7 (500ms timeout):"
"$CLI" scan \
  --vendor robstride --channel "$CAN" --transport socketcan \
  --start-id 1 --end-id 7 --feedback-ids 0xFD --timeout-ms 500 2>&1 | tail -20

echo
echo "[6] Per-motor ping (unicast, 2s timeout):"
# Same as Seeed getting-started 成品套件 1~7 扫描 — agent 禁止 write-param/id-set (docs/AGENTS.md)
models=(rs-06 rs-06 rs-06 rs-00 rs-00 rs-00 rs-00)
for i in 1 2 3 4 5 6 7; do
  m="${models[$((i - 1))]}"
  printf "  motor %d (%s): " "$i" "$m"
  if out=$("$CLI" run --vendor robstride --channel "$CAN" --transport socketcan \
      --motor-id "$i" --feedback-id 0xFD --model "$m" \
      --mode ping --timeout-ms 2000 2>&1); then
    echo "OK — $(echo "$out" | tail -1)"
  else
    echo "FAIL — $(echo "$out" | tail -3 | tr '\n' ' ')"
  fi
done

echo
echo "[7] Broadcast disable_all test (same as lerobot configure step 1):"
"$PY" - <<'PY'
import sys
try:
    from motorbridge import MotorController
    from motorbridge.transport import SocketCanTransport
except ImportError:
    sys.exit("motorbridge python not found")
try:
    t = SocketCanTransport("can0")
    c = MotorController(t)
    c.open()
    c.disable_all()
    print("  disable_all: OK (broadcast ack received)")
except Exception as e:
    print(f"  disable_all: FAIL — {e}")
PY

echo
echo "=============================================="
echo " Done. If scan=0 but read-state OK → broadcast issue."
echo " If read-state fails on 4-7 → check CAN chain past elbow."
echo " Stop Agent before teleop: pkill -f run_api.py"
echo "=============================================="
