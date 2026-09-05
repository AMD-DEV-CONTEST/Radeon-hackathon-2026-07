#!/usr/bin/env bash
# Sync ScrewShell code to a remote ROCm instance over SSH.
# Usage:
#   SCREWSHELL_HOST=root@<instance-ip> SCREWSHELL_PORT=<ssh-port> bash scripts/deploy.sh
# Optional: SCREWSHELL_KEY=~/.ssh/<key>  SCREWSHELL_DEST=/persistent/screwshell/app
set -e
HOST="${SCREWSHELL_HOST:?set SCREWSHELL_HOST=root@<instance-ip>}"
PORT="${SCREWSHELL_PORT:?set SCREWSHELL_PORT=<ssh-port>}"
KEY="${SCREWSHELL_KEY:-$HOME/.ssh/id_ed25519}"
DEST="${SCREWSHELL_DEST:-/persistent/screwshell/app}"

ssh -i "$KEY" -p "$PORT" "$HOST" "mkdir -p $DEST"
scp -i "$KEY" -P "$PORT" -r \
  screwshell bench scripts demo_workspace requirements.txt README.md docs \
  "$HOST:$DEST/"
echo "deployed to $DEST"
echo "run UI : ssh -i $KEY -p $PORT -L 7860:localhost:7860 $HOST"
echo "         cd $DEST && source /opt/venv/bin/activate && python -m screwshell.ui.app --workspace $DEST/demo_workspace"
