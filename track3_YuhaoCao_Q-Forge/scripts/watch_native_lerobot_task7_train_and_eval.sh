#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/workspace/QVGM"
TRAIN_PID="${1:-1625675}"
TRAIN_LOG="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_50ep_20k.log"
CHECKPOINT="$PROJECT_ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k/checkpoints/020000/pretrained_model"
CHECKPOINT_ROOT="${CHECKPOINT%/pretrained_model}"
EVAL_OUTPUT="$PROJECT_ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k_eval50"
EVAL_LOG="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_50ep_20k_eval50.log"
WATCH_LOG="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_watcher.log"
VERIFY_RESULT="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_checkpoint_020000_verification.json"
HASH_RESULT="$PROJECT_ROOT/outputs/logs/native_lerobot_smolvla_task7_checkpoint_020000_sha256.txt"
CURVE_RESULT="$PROJECT_ROOT/outputs/native_lerobot_smolvla_task7_50ep_20k/training_curve.json"

mkdir -p "$PROJECT_ROOT/outputs/logs"
echo "$(date -u +%FT%TZ) watching training PID $TRAIN_PID" >> "$WATCH_LOG"

while kill -0 "$TRAIN_PID" 2>/dev/null; do
  sleep 60
done

if ! grep -q "End of training" "$TRAIN_LOG"; then
  echo "$(date -u +%FT%TZ) training exited without End of training; evaluation not started" >> "$WATCH_LOG"
  exit 1
fi

if ! "$PROJECT_ROOT/.venv-lerobot-native/bin/python" \
  "$PROJECT_ROOT/scripts/summarize_native_lerobot_training.py" \
  "$TRAIN_LOG" --log-freq 200 --expected-steps 20000 \
  --output "$CURVE_RESULT" 2>> "$WATCH_LOG"; then
  echo "$(date -u +%FT%TZ) failed to summarize complete training curve" >> "$WATCH_LOG"
  exit 1
fi

for required in \
  "$CHECKPOINT/config.json" \
  "$CHECKPOINT/model.safetensors" \
  "$CHECKPOINT/policy_preprocessor.json" \
  "$CHECKPOINT/policy_preprocessor_step_5_normalizer_processor.safetensors"; do
  if [[ ! -s "$required" ]]; then
    echo "$(date -u +%FT%TZ) missing checkpoint artifact: $required" >> "$WATCH_LOG"
    exit 1
  fi
done

if ! "$PROJECT_ROOT/.venv-lerobot-native/bin/python" \
  "$PROJECT_ROOT/scripts/verify_native_lerobot_checkpoint.py" \
  "$CHECKPOINT_ROOT" --expected-step 20000 > "$VERIFY_RESULT.tmp" 2>> "$WATCH_LOG"; then
  rm -f "$VERIFY_RESULT.tmp"
  echo "$(date -u +%FT%TZ) final checkpoint failed full verification" >> "$WATCH_LOG"
  exit 1
fi
mv "$VERIFY_RESULT.tmp" "$VERIFY_RESULT"

sha256sum \
  "$CHECKPOINT/config.json" \
  "$CHECKPOINT/model.safetensors" \
  "$CHECKPOINT/policy_preprocessor.json" \
  "$CHECKPOINT/policy_preprocessor_step_5_normalizer_processor.safetensors" \
  "$CHECKPOINT/policy_postprocessor.json" \
  "$CHECKPOINT/policy_postprocessor_step_0_unnormalizer_processor.safetensors" \
  > "$HASH_RESULT.tmp"
mv "$HASH_RESULT.tmp" "$HASH_RESULT"

echo "$(date -u +%FT%TZ) checkpoint fully verified and hashed; starting 50-state evaluation" >> "$WATCH_LOG"
exec "$PROJECT_ROOT/scripts/run_native_lerobot_task7_eval.sh" \
  "$CHECKPOINT" "$EVAL_OUTPUT" >> "$EVAL_LOG" 2>&1
