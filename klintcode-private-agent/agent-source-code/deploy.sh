#!/bin/bash
set -e

REMOTE="philip@36.150.116.220"
PORT="30394"
DEST="~/klint-code"

echo "Creating remote directory..."
ssh -p $PORT $REMOTE "mkdir -p $DEST"

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
           /home/philip/githome/flint-code/ \
           $REMOTE:$DEST/

echo "Source code synced! Starting remote compilation..."
ssh -p $PORT $REMOTE "source ~/.cargo/env && cd $DEST && cargo build --release -p klintcode-tui -p klintcode-cli"

echo "Remote compilation finished!"
