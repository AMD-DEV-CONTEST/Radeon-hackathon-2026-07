#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
SUPERVISOR_CONFIG="${2:-/persistent/douyin-amd/releases/current/deploy/amd/supervisord.conf}"
[[ -f "$ENV_FILE" ]] || { printf 'Missing environment file.\n' >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

supervisorctl -c "$SUPERVISOR_CONFIG" status
"$AMD_PYTHON" - <<'PY'
import socket
for port in (18110, 18111, 18188, 18082, 14289):
    with socket.socket() as value:
        value.settimeout(0.2)
        state = "LISTENING" if value.connect_ex(("127.0.0.1", port)) == 0 else "CLOSED"
    print(f"127.0.0.1:{port} {state}")
PY
printf 'GPU backend: %s; release: %s\n' "$SHIDU_GPU_BACKEND" "$AMD_RELEASE_DIR"
