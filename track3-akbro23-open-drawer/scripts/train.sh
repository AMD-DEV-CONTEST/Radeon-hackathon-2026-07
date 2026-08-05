#!/usr/bin/env bash
# Start the long training run, detached from this shell.
#
#   scripts/train.sh
#   STEPS=2000 SAVE_FREQ=1000 scripts/train.sh --batch_size=8
#
# Ten hours outlives an ssh session, so the run is nohup'd and its output goes
# to a timestamped log. This returns the terminal immediately; the run keeps
# going after the session closes.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# nohup inherits THIS shell's environment, so the caches, mirrors and tokens
# have to be in place before the launch rather than after it.
source scripts/instance-env.sh

STEPS="${STEPS:-10000}"
SAVE_FREQ="${SAVE_FREQ:-2500}"
pid_file=out/train.pid

# Two runs on one GPU do not fail, they just both get slower and neither is
# the run you meant to start.
if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "already running as pid $(cat "$pid_file")"
    echo "stop it with: pkill -f lerobot_train"
    exit 1
fi

mkdir -p out

# A checkpoint is bf16 weights plus 8-bit optimizer state, about 17 GB, and
# lerobot keeps every one it writes. A full disk at hour eight loses the run.
free_gb=$(df -BG --output=avail . | tail -1 | tr -dc '0-9')
want_gb=$(( 17 * (STEPS / SAVE_FREQ + 1) ))
if [ "$free_gb" -lt "$want_gb" ]; then
    echo "warning: ${free_gb}G free, expecting about ${want_gb}G of checkpoints"
fi

log="out/train-$(date +%Y%m%d-%H%M%S).log"
# </dev/null so it can never block waiting on input that will not arrive.
nohup uv run train --steps="$STEPS" --save_freq="$SAVE_FREQ" "$@" \
    > "$log" 2>&1 < /dev/null &
echo $! > "$pid_file"

echo
echo "started  pid $(cat "$pid_file")"
echo "follow   tail -f $log"
echo "check    ps -p \$(cat $pid_file) && tail -3 $log"
echo "stop     pkill -f lerobot_train"
echo "resume   scripts/train.sh --resume=true"
echo
