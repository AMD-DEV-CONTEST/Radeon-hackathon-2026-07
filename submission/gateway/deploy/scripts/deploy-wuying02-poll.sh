#!/bin/bash
# wuying02 R4-only poll loop deploy script.
# O4 is uninstalled and must not be re-enabled by this script.

set -euo pipefail

cd /root/UnionAgents

echo "=== 1. Install R4 systemd unit ==="
cp deploy/systemd/r4-wuying02.service /etc/systemd/system/ 2>/dev/null || true

echo "=== 2. Stop stale R4/O4 processes ==="
systemctl stop r4-wuying02 2>/dev/null || true
systemctl stop o4-wuying02 2>/dev/null || true
systemctl disable o4-wuying02 2>/dev/null || true
pkill -f "agent-name R4" 2>/dev/null || true
pkill -f "agent-name O4" 2>/dev/null || true
sleep 2

echo "=== 3. Start R4 only ==="
systemctl daemon-reload
systemctl enable r4-wuying02
systemctl start r4-wuying02

echo "=== 4. Verify ==="
sleep 3
systemctl status r4-wuying02 --no-pager -l | head -5
echo "--- recent logs ---"
journalctl -u r4-wuying02 --no-pager -n 10
