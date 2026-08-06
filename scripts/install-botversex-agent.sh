#!/usr/bin/env bash
# BotverseX Local Agent one-click installer (M27).
# Usage:
#   curl -fsSL https://botversex.com/api/v1/agents/install.sh?token=JWT | bash
#   bash scripts/install-botversex-agent.sh --token=JWT [--upgrade]
set -euo pipefail

BOTVERSEX_HOME="${BOTVERSEX_HOME:-$HOME/.botversex}"
VENV="$BOTVERSEX_HOME/venv"
LOG="$BOTVERSEX_HOME/install.log"
TOKEN=""
UPGRADE=false
API_BASE="${BOTVERSEX_API:-https://botversex.feispace.me/api/v1}"
AGENT_REPO="${BOTVERSEX_AGENT_REPO:-https://github.com/metahubaifeel/botversex-local-agent.git}"
PY="${PYTHON:-python3.12}"

log() { echo "[botversex-install] $*" | tee -a "$LOG"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token=*) TOKEN="${1#*=}"; shift ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --upgrade) UPGRADE=true; shift ;;
    --api=*) API_BASE="${1#*=}"; shift ;;
    -h|--help)
      cat <<EOF
BotverseX Local Agent installer

  bash install-botversex-agent.sh --token=<JWT> [--upgrade] [--api=URL]

Creates: $BOTVERSEX_HOME/{venv,agent,install.log}
EOF
      exit 0
      ;;
    *) log "unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$BOTVERSEX_HOME"
: > "$LOG"

log "=== BotverseX Local Agent install ==="
log "home=$BOTVERSEX_HOME python=$PY"

OS="$(uname -s)"
if [[ "$OS" == "Darwin" ]]; then
  log "macOS detected — CAN/udev steps skipped (stub)."
elif [[ "$OS" == "Linux" ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing system packages (may prompt for sudo once)..."
    sudo apt-get update -qq || true
    sudo apt-get install -y -qq \
      python3-venv python3-pip git can-utils \
      build-essential python3-dev ffmpeg \
      2>>"$LOG" || log "WARN: some apt packages failed — continue"
    if dpkg -l brltty 2>/dev/null | grep -q ^ii; then
      log "Removing brltty (blocks Star Arm 102 USB)..."
      sudo apt-get remove -y brltty 2>>"$LOG" || true
    fi
  fi
else
  log "Unsupported OS: $OS — continuing best-effort"
fi

AGENT_DIR="$BOTVERSEX_HOME/agent"
if [[ ! -d "$AGENT_DIR/.git" ]]; then
  log "Cloning Local Agent..."
  git clone --depth 1 "$AGENT_REPO" "$AGENT_DIR" 2>>"$LOG"
elif [[ "$UPGRADE" == true ]]; then
  log "Updating Local Agent..."
  git -C "$AGENT_DIR" pull --ff-only 2>>"$LOG" || true
else
  log "Agent repo exists — skip clone (use --upgrade to pull)"
fi

# Sync B601 URDF assets when installing from monorepo checkout
MONOREPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -d "$MONOREPO_ROOT/apps/realtime/static/urdf/b601_rs" ]]; then
  log "Syncing B601 URDF assets from monorepo..."
  mkdir -p "$AGENT_DIR/static/urdf/b601_rs"
  cp -r "$MONOREPO_ROOT/apps/realtime/static/urdf/b601_rs/"* "$AGENT_DIR/static/urdf/b601_rs/" 2>>"$LOG" || true
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  log "Creating venv at $VENV ..."
  "$PY" -m venv "$VENV" 2>>"$LOG"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip wheel setuptools >>"$LOG" 2>&1

PIP_INDEX="${BOTVERSEX_PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
log "Installing Local Agent requirements..."
pip install -r "$AGENT_DIR/requirements.txt" \
  -i "$PIP_INDEX" --timeout 120 >>"$LOG" 2>&1 || \
  pip install -r "$AGENT_DIR/requirements.txt" --timeout 120 >>"$LOG" 2>&1

log "Installing B601-RS official plugins..."
pip install \
  lerobot-robot-seeed-b601 \
  lerobot-teleoperator-rebot-arm-102 \
  'motorbridge>=0.4.8' \
  -i "$PIP_INDEX" --timeout 120 >>"$LOG" 2>&1 || \
  pip install lerobot-robot-seeed-b601 lerobot-teleoperator-rebot-arm-102 motorbridge >>"$LOG" 2>&1

if [[ "$OS" == "Linux" ]] && command -v apt-get >/dev/null 2>&1; then
  UDEV="/etc/udev/rules.d/99-botversex.rules"
  if [[ ! -f "$UDEV" ]]; then
    log "Writing udev rules (sudo once)..."
    sudo tee "$UDEV" >/dev/null <<'UDEV'
# BotverseX — Star Arm 102 leader (FTDI / CP210x common IDs; adjust if needed)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", SYMLINK+="leader_stararm102", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="leader_stararm102", MODE="0666", GROUP="dialout"
# PCAN-USB
SUBSYSTEM=="usb", ATTRS{idVendor}=="0c72", MODE="0666", GROUP="dialout"
UDEV
    sudo udevadm control --reload-rules
    sudo udevadm trigger
  fi

  CAN_UNIT="/etc/systemd/system/botversex-can@.service"
  if [[ ! -f "$CAN_UNIT" ]]; then
    log "Installing systemd CAN unit..."
    sudo tee "$CAN_UNIT" >/dev/null <<'UNIT'
[Unit]
Description=BotverseX CAN interface %i
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/sbin/modprobe peak_usb
ExecStart=/sbin/ip link set %i down
ExecStart=/sbin/ip link set %i type can bitrate 1000000 restart-ms 100
ExecStart=/sbin/ip link set %i up

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl enable "botversex-can@can0.service" 2>>"$LOG" || true
    sudo systemctl start "botversex-can@can0.service" 2>>"$LOG" || log "WARN: CAN start failed — plug PCAN and retry"
  fi

  AGENT_UNIT="/etc/systemd/system/botversex-agent.service"
  if [[ ! -f "$AGENT_UNIT" ]]; then
    log "Installing systemd Agent unit..."
    sudo tee "$AGENT_UNIT" >/dev/null <<UNIT
[Unit]
Description=BotverseX Local Agent
After=network.target botversex-can@can0.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$AGENT_DIR
Environment=BOTVERSEX_HOME=$BOTVERSEX_HOME
Environment=PATH=$VENV/bin:/usr/bin:/bin
ExecStart=$VENV/bin/python $AGENT_DIR/run_api.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable botversex-agent.service 2>>"$LOG" || true
  fi
fi

if [[ -n "$TOKEN" ]]; then
  log "Registering agent with cloud..."
  curl -fsS -X POST "$API_BASE/agents/register" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"hostname\":\"$(hostname)\",\"platform\":\"$OS\"}" \
    >>"$LOG" 2>&1 || log "WARN: cloud registration failed — agent still runs locally"
fi

log "Starting Local Agent..."
if systemctl is-enabled botversex-agent.service >/dev/null 2>&1; then
  sudo systemctl restart botversex-agent.service 2>>"$LOG" || true
else
  cd "$AGENT_DIR"
  nohup "$VENV/bin/python" run_api.py >>"$BOTVERSEX_HOME/agent.log" 2>&1 &
  log "Agent PID $! — log: $BOTVERSEX_HOME/agent.log"
fi

log "Done. Open https://localhost:8002/api/setup/health or your BotverseX web console."
log "B601 page: /robots/b601_rs"
