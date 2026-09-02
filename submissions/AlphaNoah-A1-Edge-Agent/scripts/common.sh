#!/usr/bin/env bash
set -euo pipefail
PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$PACKAGE_ROOT/config/alphanoah.env"
PID_FILE="$PACKAGE_ROOT/data/alphanoah.pid"
LOG_FILE="$PACKAGE_ROOT/logs/alphanoah.log"

load_config() {
  [[ -f "$CONFIG_FILE" ]] || { echo "Configuration missing. Run ./scripts/configure.sh"; exit 2; }
  set -a
  # This file is created locally with mode 600. Do not copy untrusted files here.
  source "$CONFIG_FILE"
  set +a
  ALPHANOAH_PORT="${ALPHANOAH_PORT:-8090}"
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(<"$PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

endpoint_scope() {
  "$PACKAGE_ROOT/.venv/bin/python" - "$1" <<\PY
import ipaddress, sys
from urllib.parse import urlsplit
host = (urlsplit(sys.argv[1]).hostname or "").lower()
if host == "localhost": print("This device")
else:
    try: address = ipaddress.ip_address(host)
    except ValueError: print("External network")
    else: print("This device" if address.is_loopback else "Enterprise LAN" if address.is_private else "External network")
PY
}
