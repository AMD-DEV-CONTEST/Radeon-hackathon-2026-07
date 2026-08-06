#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi
EVEROS_REPOSITORY="${EVEROS_REPOSITORY:-https://github.com/EverMind-AI/EverOS.git}"
EVEROS_REF="v1.2.0"
EVEROS_COMMIT="64e0fdc9bbce996f751f053cff2a21809a46cd35"
PREFIX="$PROJECT_ROOT/.runtime/everos"
DATA_ROOT="${EVEROS_ROOT:-${MEMORY_DATA_ROOT:-$PROJECT_ROOT/.runtime}/everos}"
PORT="8001"
INSTALL_SYSTEMD=0

usage() {
  cat <<'EOF'
Usage: scripts/install-everos-linux.sh [options]

Options:
  --prefix PATH       EverOS source/runtime checkout.
  --data-root PATH    Durable EverOS data directory.
  --port PORT         Loopback API port (default: 8001).
  --systemd           Install and start the systemd service.
  --help              Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --prefix)
      PREFIX="$2"
      shift 2
      ;;
    --data-root)
      DATA_ROOT="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --systemd)
      INSTALL_SYSTEMD=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || {
  echo "Port must be between 1 and 65535." >&2
  exit 2
}

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 1; }
command -v uv >/dev/null 2>&1 || { echo "uv is required" >&2; exit 1; }

if [[ -e "$PREFIX" && ! -d "$PREFIX/.git" ]]; then
  echo "EverOS prefix exists but is not a Git checkout: $PREFIX" >&2
  exit 1
fi

if [[ ! -d "$PREFIX/.git" ]]; then
  mkdir -p "$(dirname "$PREFIX")"
  git clone \
    --filter=blob:none \
    --branch "$EVEROS_REF" \
    --single-branch \
    "$EVEROS_REPOSITORY" \
    "$PREFIX"
fi

TAG_COMMIT="$(git -C "$PREFIX" rev-parse "$EVEROS_REF^{}")"
CURRENT_COMMIT="$(git -C "$PREFIX" rev-parse HEAD)"
if [[ "$TAG_COMMIT" != "$EVEROS_COMMIT" ]]; then
  echo "EverOS tag $EVEROS_REF resolves to $TAG_COMMIT; expected $EVEROS_COMMIT" >&2
  exit 1
fi
if [[ "$CURRENT_COMMIT" != "$EVEROS_COMMIT" ]]; then
  echo "EverOS checkout is at $CURRENT_COMMIT; expected $EVEROS_COMMIT" >&2
  exit 1
fi

if [[ ! -x "$PREFIX/.venv/bin/everos" ]]; then
  uv venv --python python3.12 "$PREFIX/.venv"
fi
uv pip install --python "$PREFIX/.venv/bin/python" -e "$PREFIX[multimodal]"

for PATCH_FILE in "$PROJECT_ROOT"/tools/everos/patches/*.patch; do
  [[ -f "$PATCH_FILE" ]] || continue
  if git -C "$PREFIX" apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
    continue
  fi
  git -C "$PREFIX" apply --check "$PATCH_FILE"
  git -C "$PREFIX" apply "$PATCH_FILE"
done

mkdir -p "$DATA_ROOT"
if [[ ! -f "$DATA_ROOT/everos.toml" ]]; then
  "$PREFIX/.venv/bin/everos" init --root "$DATA_ROOT"
fi

if [[ "$INSTALL_SYSTEMD" -eq 1 ]]; then
  [[ -f "$PROJECT_ROOT/.env" ]] || {
    echo "Missing $PROJECT_ROOT/.env; configure it before installing systemd." >&2
    exit 1
  }
  TEMPLATE="$PROJECT_ROOT/scripts/systemd/beaver-everos.service.in"
  BRIDGE_TEMPLATE="$PROJECT_ROOT/scripts/systemd/beaver-provider-bridge.service.in"
  RENDERED="$(mktemp)"
  BRIDGE_RENDERED="$(mktemp)"
  trap 'rm -f "$RENDERED" "$BRIDGE_RENDERED"' EXIT
  sed \
    -e "s#@@PROJECT_ROOT@@#$PROJECT_ROOT#g" \
    -e "s#@@PREFIX@@#$PREFIX#g" \
    -e "s#@@DATA_ROOT@@#$DATA_ROOT#g" \
    -e "s#@@PORT@@#$PORT#g" \
    -e "s#@@USER@@#$(id -un)#g" \
    "$TEMPLATE" > "$RENDERED"
  sed \
    -e "s#@@PROJECT_ROOT@@#$PROJECT_ROOT#g" \
    -e "s#@@USER@@#$(id -un)#g" \
    "$BRIDGE_TEMPLATE" > "$BRIDGE_RENDERED"
  sudo install -m 0644 "$BRIDGE_RENDERED" /etc/systemd/system/beaver-provider-bridge.service
  sudo install -m 0644 "$RENDERED" /etc/systemd/system/beaver-everos.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now beaver-provider-bridge.service
  sudo systemctl enable --now beaver-everos.service
fi

HEALTH_URL="http://127.0.0.1:$PORT/health"
if command -v curl >/dev/null 2>&1 && curl --silent --fail --max-time 2 "$HEALTH_URL" >/dev/null; then
  echo "READY EverOS $HEALTH_URL"
else
  echo "INSTALLED EverOS; health is not ready at $HEALTH_URL"
fi
echo "EVEROS_BASE_URL=http://127.0.0.1:$PORT"
