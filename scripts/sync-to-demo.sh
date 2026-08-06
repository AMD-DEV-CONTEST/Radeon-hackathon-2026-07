#!/usr/bin/env bash
# Push BotverseX source + demo config from Linux dev machine to Windows presentation laptop.
#
# Prerequisites on Windows:
#   - OpenSSH Server enabled (Settings → Apps → Optional features → OpenSSH Server)
#   - Same user can write to C:/Users/Public/dev/botversex
#   - SSH key: ~/.ssh/reachy_lenovo (or set DEMO_SSH_KEY)
#
# Usage:
#   DEMO_SSH_HOST=amd@192.168.x.x bash scripts/sync-to-demo.sh
#   DEMO_SSH_HOST=reachy-demo bash scripts/sync-to-demo.sh   # if ~/.ssh/config has Host reachy-demo
#   SYNC_KEYS=1 DEMO_SSH_HOST=... bash scripts/sync-to-demo.sh   # also copy Seeed keys + conversation patches
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${DEMO_SSH_HOST:-}"
KEY="${DEMO_SSH_KEY:-$HOME/.ssh/reachy_lenovo}"
REMOTE_DIR="${DEMO_REMOTE_DIR:-C:/Users/AMD/dev/botversex}"
SYNC_KEYS="${SYNC_KEYS:-0}"

if [ -z "$HOST" ]; then
  echo "Set DEMO_SSH_HOST=amd@<windows-ip>"
  echo "Example: DEMO_SSH_HOST=amd@192.168.57.100 bash scripts/sync-to-demo.sh"
  exit 1
fi

SSH=(ssh -o ConnectTimeout=10)
RSYNC=(rsync -az --delete --info=progress2)
if [ -f "$KEY" ]; then
  SSH+=(-i "$KEY")
  RSYNC+=(-e "ssh -i $KEY")
fi

echo "[sync] packaging source (no venv/node_modules) ..."
ARCHIVE="$(mktemp /tmp/botversex-sync-XXXXXX.tar.gz)"
bash "$ROOT/scripts/package-source.sh" "$ARCHIVE"

echo "[sync] ensuring remote dir $REMOTE_DIR ..."
"${SSH[@]}" "$HOST" "if not exist \"${REMOTE_DIR//\//\\}\" mkdir \"${REMOTE_DIR//\//\\}\""

echo "[sync] uploading archive ..."
if [ -f "$KEY" ]; then
  scp -i "$KEY" "$ARCHIVE" "$HOST:/tmp/botversex-sync.tar.gz"
else
  scp "$ARCHIVE" "$HOST:/tmp/botversex-sync.tar.gz"
fi

echo "[sync] extracting on Windows ..."
"${SSH[@]}" "$HOST" "cd '$(dirname "$REMOTE_DIR")' && tar -xzf /tmp/botversex-sync.tar.gz && rm /tmp/botversex-sync.tar.gz"

if [ -f "$ROOT/apps/api/.env" ]; then
  echo "[sync] copying apps/api/.env (secrets) ..."
  scp -i "$KEY" "$ROOT/apps/api/.env" "$HOST:$REMOTE_DIR/apps/api/.env" 2>/dev/null || \
    scp "$ROOT/apps/api/.env" "$HOST:$REMOTE_DIR/apps/api/.env"
fi

if [ "$SYNC_KEYS" = 1 ]; then
  KEYS="$HOME/.config/botversex/reachy_seeed_keys.json"
  SEEED="$HOME/.local/share/botversex/seeed_reachymini_conversation"
  if [ -f "$KEYS" ]; then
    echo "[sync] Seeed API keys ..."
    "${SSH[@]}" "$HOST" "mkdir -p '/c/Users/$(echo "$HOST" | cut -d@ -f1)/.config/botversex'"
    scp -i "$KEY" "$KEYS" "$HOST:/c/Users/Public/.config/botversex/reachy_seeed_keys.json" 2>/dev/null || true
  fi
  if [ -d "$SEEED" ]; then
    echo "[sync] Seeed conversation tree (may take a minute) ..."
    "${RSYNC[@]}" "$SEEED/" "$HOST:/c/Users/Public/botversex/seeed_reachymini_conversation/"
  fi
fi

rm -f "$ARCHIVE"

echo ""
echo "[sync] done. On Windows run:"
echo "  cd C:\\Users\\Public\\dev\\botversex"
echo "  .\\scripts\\windows\\setup-first.ps1    # first time only"
echo "  .\\scripts\\windows\\dev-all.ps1 up"
