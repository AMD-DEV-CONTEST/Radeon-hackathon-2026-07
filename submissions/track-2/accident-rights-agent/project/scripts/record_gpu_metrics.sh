#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

duration_seconds="${1:-120}"
interval_seconds="${2:-1}"
output_path="${3:-artifacts/amd-smi-$(date -u +%Y%m%dT%H%M%SZ).log}"

if ! [[ "$duration_seconds" =~ ^[0-9]+$ ]] || (( duration_seconds < 1 )); then
  echo "ERROR: duration must be a positive integer." >&2
  exit 2
fi
if ! [[ "$interval_seconds" =~ ^[0-9]+$ ]] || (( interval_seconds < 1 )); then
  echo "ERROR: interval must be a positive integer." >&2
  exit 2
fi
if ! command -v amd-smi >/dev/null 2>&1; then
  echo "ERROR: amd-smi not found." >&2
  echo "NEXT: select the official Radeon/ROCm image and rerun the environment fingerprint." >&2
  exit 127
fi

mkdir -p "$(dirname "$output_path")"
iterations=$(( (duration_seconds + interval_seconds - 1) / interval_seconds ))

{
  printf 'record_started_at_utc=%s\n' "$(date -u +%FT%TZ)"
  printf 'duration_seconds=%s\n' "$duration_seconds"
  printf 'interval_seconds=%s\n' "$interval_seconds"
  for ((iteration=1; iteration<=iterations; iteration++)); do
    printf '\n--- sample=%s captured_at_utc=%s ---\n' \
      "$iteration" "$(date -u +%FT%TZ)"
    if ! amd-smi metric --gpu all; then
      echo "metric_command_failed=true"
      echo "NEXT: run 'amd-smi --help' and adapt this script to the installed AMD SMI version."
      exit 1
    fi
    if (( iteration < iterations )); then
      sleep "$interval_seconds"
    fi
  done
  printf '\nrecord_finished_at_utc=%s\n' "$(date -u +%FT%TZ)"
} | tee "$output_path"

echo "Saved GPU metrics: $output_path"
