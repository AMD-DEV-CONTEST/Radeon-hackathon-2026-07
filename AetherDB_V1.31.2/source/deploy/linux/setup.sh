#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_NAME="aetherdb-local"
SERVICE_TEMPLATE="${APP_DIR}/deploy/linux/systemd/worldview.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_DIR="/etc/aetherdb"
ENV_FILE="${ENV_DIR}/${SERVICE_NAME}.env"
RUNTIME_ROOT="${AETHERDB_RUNTIME_ROOT:-/var/lib/aetherdb}"
REQUESTED_PORT="${AETHERDB_PORT:-0}"

fail() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

if [[ "${EUID}" -eq 0 ]]; then
  fail "Run as an ordinary sudo-capable user, not directly as root."
fi
command -v sudo >/dev/null 2>&1 || fail "sudo is required."
[[ -f /etc/debian_version ]] || fail "This helper supports Debian/Ubuntu only."
[[ "${RUNTIME_ROOT}" = /* ]] || fail "AETHERDB_RUNTIME_ROOT must be absolute."
[[ "${REQUESTED_PORT}" =~ ^[0-9]+$ ]] || fail "AETHERDB_PORT must be an integer."
(( REQUESTED_PORT >= 0 && REQUESTED_PORT <= 65535 )) || fail "AETHERDB_PORT is outside 0..65535."
(( REQUESTED_PORT != 8000 )) || fail "Legacy fixed port 8000 is not allowed."

printf '%s\n' "=== AetherDB V1.31.2 local Linux service setup ==="
printf '%s\n' "This installs a loopback-only validation API, not a public server."
printf '%s\n' "Use the Tauri DEB/AppImage for the graphical application."

sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

if [[ ! -d "${APP_DIR}/venv" ]]; then
  python3 -m venv "${APP_DIR}/venv"
fi
"${APP_DIR}/venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

PORT="${REQUESTED_PORT}"
if (( PORT == 0 )); then
  PORT="$("${APP_DIR}/venv/bin/python" -c \
    'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
[[ "${PORT}" =~ ^[0-9]+$ ]] || fail "Could not allocate a loopback port."
(( PORT >= 1 && PORT <= 65535 && PORT != 8000 )) || fail "Allocated port is invalid."

if ! id -u aetherdb >/dev/null 2>&1; then
  sudo useradd --system --home-dir "${RUNTIME_ROOT}" --shell /usr/sbin/nologin aetherdb
fi
sudo install -d -m 0700 -o aetherdb -g aetherdb "${RUNTIME_ROOT}"
sudo install -d -m 0750 -o root -g aetherdb "${ENV_DIR}"

sudo tee "${ENV_FILE}" >/dev/null <<EOF
AETHERDB_RESOURCE_ROOT="${APP_DIR}"
AETHERDB_RUNTIME_ROOT="${RUNTIME_ROOT}"
AETHERDB_DEPLOYMENT_MODE="local_desktop"
AETHERDB_HOST="127.0.0.1"
AETHERDB_PORT="${PORT}"
PYTHONUNBUFFERED="1"
PYTHONUTF8="1"
EOF
sudo chmod 0640 "${ENV_FILE}"
sudo chown root:aetherdb "${ENV_FILE}"

escaped_app="${APP_DIR//|/\\|}"
escaped_runtime="${RUNTIME_ROOT//|/\\|}"
sed \
  -e "s|@AETHERDB_APP_DIR@|${escaped_app}|g" \
  -e "s|@AETHERDB_RUNTIME_ROOT@|${escaped_runtime}|g" \
  "${SERVICE_TEMPLATE}" | sudo tee "${SERVICE_FILE}" >/dev/null
sudo chmod 0644 "${SERVICE_FILE}"

sudo -u aetherdb env \
  AETHERDB_RESOURCE_ROOT="${APP_DIR}" \
  AETHERDB_RUNTIME_ROOT="${RUNTIME_ROOT}" \
  AETHERDB_DEPLOYMENT_MODE="local_desktop" \
  PYTHONUTF8=1 \
  "${APP_DIR}/venv/bin/python" "${APP_DIR}/scripts/init_runtime.py"

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

ready=0
for _attempt in $(seq 1 120); do
  if "${APP_DIR}/venv/bin/python" -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/api/auth/status', timeout=2)" \
    >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if (( ready == 0 )); then
  sudo systemctl stop "${SERVICE_NAME}" || true
  fail "Service readiness timed out after 120 seconds. Inspect journalctl -u ${SERVICE_NAME}."
fi

printf '[OK] Local validation API: http://127.0.0.1:%s\n' "${PORT}"
printf '[OK] Status: systemctl status %s\n' "${SERVICE_NAME}"
printf '%s\n' "No firewall rule or public reverse proxy was created."
