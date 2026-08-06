#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
[[ -f "$ENV_FILE" ]] || { printf 'Missing environment file.\n' >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

probe() {
  curl --fail --silent --show-error --max-time 10 "$1" >/dev/null
}

probe http://127.0.0.1:18110/health
probe http://127.0.0.1:18111/health
probe http://127.0.0.1:18082/health/live
probe http://127.0.0.1:18082/health/ready
probe http://127.0.0.1:14289/
if "$AMD_PYTHON" - <<'PY'
import socket
with socket.socket() as value:
    value.settimeout(0.2)
    raise SystemExit(0 if value.connect_ex(("127.0.0.1", 18188)) == 0 else 1)
PY
then
  printf 'ComfyUI must remain stopped before the user click.\n' >&2
  exit 1
fi
printf 'AMD CPU loopback smoke checks passed; GPU remains stopped.\n'
