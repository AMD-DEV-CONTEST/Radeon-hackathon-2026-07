#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/app.yaml}"
ITERATIONS="${BUILDGUARD_AGENT_ITERATIONS:-20}"
TOOL_ITERATIONS="${BUILDGUARD_TOOL_ITERATIONS:-50}"

case "$ITERATIONS" in
  ''|*[!0-9]*)
    echo "BUILDGUARD_AGENT_ITERATIONS must be a positive integer." >&2
    exit 2
    ;;
esac
case "$TOOL_ITERATIONS" in
  ''|*[!0-9]*)
    echo "BUILDGUARD_TOOL_ITERATIONS must be a positive integer." >&2
    exit 2
    ;;
esac
if [ "$ITERATIONS" -le 0 ] || [ "$TOOL_ITERATIONS" -le 0 ]; then
  echo "Benchmark iteration counts must be positive." >&2
  exit 2
fi

index=1
failures=0
while [ "$index" -le "$ITERATIONS" ]; do
  if ! buildguard smoke-test --config "$CONFIG_PATH"; then
    failures=$((failures + 1))
  fi
  index=$((index + 1))
done

if [ "$failures" -ne 0 ]; then
  echo "$failures of $ITERATIONS Agent smoke tasks failed." >&2
  exit 2
fi

buildguard tool-stability --config "$CONFIG_PATH" \
  --iterations "$TOOL_ITERATIONS"
buildguard benchmark-suite --config "$CONFIG_PATH" --section agent
