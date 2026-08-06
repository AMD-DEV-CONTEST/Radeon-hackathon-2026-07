#!/usr/bin/env bash
# B601 + PCAN-USB: bring up SocketCAN at 1 Mbps (requires sudo).
# Run once after each reboot, or add to systemd — see wiki:
# https://wiki.seeedstudio.com/rebot_b601_rs_getting_started/
set -euo pipefail

IFACE="${1:-can0}"
BITRATE="${2:-1000000}"

echo "[rebot] loading peak_usb kernel module..."
sudo modprobe peak_usb

echo "[rebot] CAN interfaces:"
ip -br link | grep -E '^can' || true

if ! ip link show "$IFACE" &>/dev/null; then
  echo "[rebot] ERROR: $IFACE not found. Is PCAN-USB plugged in?"
  echo "        lsusb | grep -i peak"
  exit 1
fi

echo "[rebot] configuring $IFACE @ ${BITRATE} bps..."
sudo ip link set "$IFACE" down 2>/dev/null || true
sudo ip link set "$IFACE" type can bitrate "$BITRATE" restart-ms 100
sudo ip link set "$IFACE" up

echo "[rebot] done:"
ip -details link show "$IFACE" | head -6
