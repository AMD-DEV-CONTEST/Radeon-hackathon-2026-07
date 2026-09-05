#!/bin/bash
set -euo pipefail

REMOTE="${KLINTCODE_REMOTE:?Set KLINTCODE_REMOTE to user@host}"
PORT="${KLINTCODE_SSH_PORT:-22}"
DEST="${KLINTCODE_REMOTE_DIR:-klint-code}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${KLINTCODE_SOURCE_DIR:-$SCRIPT_DIR/}"

echo "Creating remote directory..."
ssh -p "$PORT" "$REMOTE" "mkdir -p $DEST"

echo "Syncing source code..."
rsync -avz --exclude 'target' \
           --exclude 'build' \
           --exclude '.git' \
           --exclude 'benchmark_logs' \
           --exclude 'runs' \
           --exclude 'showcase' \
           --exclude '30obj-success-output' \
           --exclude '*.log' \
           -e "ssh -p $PORT" \
           "$SOURCE_DIR" \
           "$REMOTE:$DEST/"

echo "Source code synced! Starting remote compilation..."
ssh -p "$PORT" "$REMOTE" "source ~/.cargo/env && cd $DEST && cargo build --release -p klintcode-tui -p klintcode-cli"

echo "Remote compilation finished!"
