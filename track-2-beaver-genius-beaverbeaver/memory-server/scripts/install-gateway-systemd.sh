#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="beaver-memory-gateway.service"
TEMPLATE="$PROJECT_ROOT/scripts/systemd/$SERVICE_NAME.in"
TARGET="/etc/systemd/system/$SERVICE_NAME"
TEMP_FILE="$(mktemp)"
trap 'rm -f "$TEMP_FILE"' EXIT

sed \
  -e "s#@@PROJECT_ROOT@@#$PROJECT_ROOT#g" \
  -e "s#@@USER@@#$(id -un)#g" \
  "$TEMPLATE" > "$TEMP_FILE"

sudo install -m 0644 "$TEMP_FILE" "$TARGET"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl --no-pager --full status "$SERVICE_NAME"
