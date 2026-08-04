#!/usr/bin/env bash
set -u

INSTALLER="/var/run/secrets/frp-self-service/install"
IDENTITY_DIR="/var/run/secrets/frp-self-service"
RC_TUNNEL="${HOME}/.local/bin/rc-tunnel"
PORT="8000"
OUTPUT_PATH=""

usage() {
  printf '%s\n' "safe diagnostic: usage check_rc_tunnel_prerequisites.sh [--port PORT] [--output PATH]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --port)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      PORT="$2"
      shift 2
      ;;
    --output)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf '%s\n' "safe diagnostic: unsupported argument"
      exit 2
      ;;
  esac
done

installer_exists=false
installer_executable=false
identity_directory_exists=false
broker_setting_present=false
rc_tunnel_installed=false
rc_tunnel_version_works=false
port_valid=false
backend_listening=false
tunnel_active=false
version=""

[ -f "$INSTALLER" ] && installer_exists=true
[ -x "$INSTALLER" ] && installer_executable=true
[ -d "$IDENTITY_DIR" ] && identity_directory_exists=true
[ -n "${FRP_BROKER_URL:-}" ] && broker_setting_present=true

if [ -x "$RC_TUNNEL" ]; then
  rc_tunnel_installed=true
  if version_output="$("$RC_TUNNEL" version 2>/dev/null)"; then
    rc_tunnel_version_works=true
    version="$(printf '%s' "$version_output" | grep -Eo 'v?[0-9]+\.[0-9]+(\.[0-9]+)?([.-][A-Za-z0-9]+)*' | head -n 1 || true)"
  fi
  status_output="$("$RC_TUNNEL" status 2>/dev/null || true)"
  if printf '%s' "$status_output" | grep -Eqi '(^|[[:space:]])(active|running)([[:space:]]|$)'; then
    tunnel_active=true
  fi
fi

if printf '%s' "$PORT" | grep -Eq '^[0-9]+$' && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ]; then
  port_valid=true
  if command -v curl >/dev/null 2>&1 &&
    curl --silent --show-error --output /dev/null --max-time 2 \
      "http://127.0.0.1:${PORT}/health" 2>/dev/null; then
    backend_listening=true
  fi
fi

if [ "$installer_exists" = true ]; then
  printf '%s\n' "tunnel installer: available"
else
  printf '%s\n' "tunnel installer: unavailable"
fi
if [ "$installer_executable" = true ]; then
  printf '%s\n' "tunnel installer executable: available"
else
  printf '%s\n' "tunnel installer executable: unavailable"
fi
if [ "$identity_directory_exists" = true ]; then
  printf '%s\n' "tunnel identity prerequisites: available"
else
  printf '%s\n' "tunnel identity prerequisites: unavailable"
fi
if [ "$broker_setting_present" = true ]; then
  printf '%s\n' "tunnel broker setting: available"
else
  printf '%s\n' "tunnel broker setting: unavailable"
fi
if [ "$rc_tunnel_installed" = true ]; then
  printf '%s\n' "tunnel command: already installed"
else
  printf '%s\n' "tunnel command: unavailable"
fi
if [ "$rc_tunnel_version_works" = true ]; then
  printf '%s\n' "tunnel version check: available"
else
  printf '%s\n' "tunnel version check: unavailable"
fi
if [ "$port_valid" = true ]; then
  printf '%s\n' "selected port: available"
else
  printf '%s\n' "selected port: unavailable"
fi
if [ "$backend_listening" = true ]; then
  printf '%s\n' "loopback backend: available"
else
  printf '%s\n' "loopback backend: backend unavailable"
fi
if [ "$tunnel_active" = true ]; then
  printf '%s\n' "existing tunnel: available"
else
  printf '%s\n' "existing tunnel: unavailable"
fi

if [ -n "$OUTPUT_PATH" ]; then
  output_parent="$(dirname -- "$OUTPUT_PATH")"
  mkdir -p -- "$output_parent"
  temporary_output="$(mktemp "${output_parent}/.rc-tunnel-check.XXXXXX")"
  trap 'rm -f -- "${temporary_output:-}"' EXIT
  RC_CHECK_OUTPUT="$temporary_output" \
  RC_INSTALLER_EXISTS="$installer_exists" \
  RC_INSTALLER_EXECUTABLE="$installer_executable" \
  RC_IDENTITY_EXISTS="$identity_directory_exists" \
  RC_BROKER_PRESENT="$broker_setting_present" \
  RC_INSTALLED="$rc_tunnel_installed" \
  RC_VERSION_WORKS="$rc_tunnel_version_works" \
  RC_VERSION="$version" \
  RC_PORT_VALID="$port_valid" \
  RC_BACKEND_LISTENING="$backend_listening" \
  RC_TUNNEL_ACTIVE="$tunnel_active" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

def flag(name: str) -> bool:
    return os.environ[name] == "true"

payload = {
    "installer_exists": flag("RC_INSTALLER_EXISTS"),
    "installer_executable": flag("RC_INSTALLER_EXECUTABLE"),
    "identity_directory_exists": flag("RC_IDENTITY_EXISTS"),
    "broker_setting_present": flag("RC_BROKER_PRESENT"),
    "rc_tunnel_installed": flag("RC_INSTALLED"),
    "rc_tunnel_version_works": flag("RC_VERSION_WORKS"),
    "rc_tunnel_version": os.environ["RC_VERSION"] or None,
    "port_valid": flag("RC_PORT_VALID"),
    "backend_listening_loopback": flag("RC_BACKEND_LISTENING"),
    "existing_tunnel_active": flag("RC_TUNNEL_ACTIVE"),
}
Path(os.environ["RC_CHECK_OUTPUT"]).write_text(
    json.dumps(payload, indent=2) + "\n",
    encoding="utf-8",
)
PY
  mv -- "$temporary_output" "$OUTPUT_PATH"
  trap - EXIT
fi

if [ "$installer_exists" = true ] &&
  [ "$installer_executable" = true ] &&
  [ "$identity_directory_exists" = true ] &&
  [ "$broker_setting_present" = true ] &&
  [ "$port_valid" = true ]; then
  exit 0
fi
exit 1
