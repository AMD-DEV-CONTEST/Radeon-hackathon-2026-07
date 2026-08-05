#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/workspace/QVGM"
STEP="${1:?usage: $0 STEP [TRAIN_PID]}"
TRAIN_PID="${2:-1625675}"
PADDED_STEP="$(printf '%06d' "$STEP")"
CHECKPOINT="$PROJECT_ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k/checkpoints/$PADDED_STEP"
RESULT="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_checkpoint_${PADDED_STEP}_verification.json"
WATCH_LOG="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_checkpoint_watcher.log"

mkdir -p "$PROJECT_ROOT/outputs/logs"
echo "$(date -u +%FT%TZ) waiting for checkpoint $PADDED_STEP" >> "$WATCH_LOG"

while kill -0 "$TRAIN_PID" 2>/dev/null; do
  if [[ -s "$CHECKPOINT/training_state/training_step.json" ]]; then
    # LeRobot writes the step marker last enough for the verifier to distinguish
    # an incomplete directory; retry briefly if filesystem writes are still settling.
    for _ in $(seq 1 12); do
      if "$PROJECT_ROOT/.venv-lerobot-native/bin/python" \
        "$PROJECT_ROOT/scripts/verify_native_lerobot_checkpoint.py" \
        "$CHECKPOINT" --expected-step "$STEP" > "$RESULT.tmp" 2>> "$WATCH_LOG"; then
        mv "$RESULT.tmp" "$RESULT"
        echo "$(date -u +%FT%TZ) checkpoint $PADDED_STEP verified" >> "$WATCH_LOG"
        exit 0
      fi
      sleep 10
    done
    rm -f "$RESULT.tmp"
    echo "$(date -u +%FT%TZ) checkpoint $PADDED_STEP failed verification" >> "$WATCH_LOG"
    exit 1
  fi
  sleep 30
done

echo "$(date -u +%FT%TZ) training exited before checkpoint $PADDED_STEP was verified" >> "$WATCH_LOG"
exit 1
