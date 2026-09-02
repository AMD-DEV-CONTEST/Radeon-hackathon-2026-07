#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile_id="${1:-}"
benchmark_bin="${SIGNALFORGE_BENCHMARK_BIN:-$repo_root/bin/signalforge-benchmark}"
output_root="${SIGNALFORGE_OPTIMIZATION_OUTPUT_ROOT:-$repo_root/evidence/runs/sprint11}"
output_dir="$output_root/$profile_id"
server_log="$output_dir/server.log"
server_pid_file="$output_dir/server.pid"

if [[ -z "$profile_id" ]]; then
  echo "Usage: scripts/run_radeon_profile.sh PROFILE_ID" >&2
  exit 2
fi
if [[ ! -x "$benchmark_bin" ]]; then
  echo "Benchmark binary is unavailable: $benchmark_bin" >&2
  exit 1
fi

mkdir -p "$output_dir"

existing_pids="$(pgrep -f "$repo_root/runtime/llama.cpp/build-rocm/bin/llama-server" || true)"
if [[ -n "$existing_pids" ]]; then
  while read -r pid; do
    [[ -n "$pid" ]] && kill -TERM "$pid"
  done <<< "$existing_pids"
  for _ in $(seq 1 30); do
    pgrep -f "$repo_root/runtime/llama.cpp/build-rocm/bin/llama-server" >/dev/null || break
    sleep 1
  done
fi

started_ns="$(date +%s%N)"
"$repo_root/scripts/serve_llama_rocm.sh" >"$server_log" 2>&1 &
server_pid="$!"
printf '%s\n' "$server_pid" > "$server_pid_file"

cleanup() {
  if kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

ready=0
for _ in $(seq 1 120); do
  if curl -fsS "http://127.0.0.1:${SIGNALFORGE_MODEL_PORT:-8000}/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "llama-server exited before readiness" >&2
    tail -80 "$server_log" >&2
    exit 1
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "llama-server did not become ready in 120 seconds" >&2
  exit 1
fi
ready_ns="$(date +%s%N)"
printf '%s\n' "$(( (ready_ns - started_ns) / 1000000 ))" > "$output_dir/startup-ready-ms.txt"

run_measurement() {
  local mode="$1"
  local concurrency="$2"
  local prefix="$output_dir/$mode"

  curl -fsS "http://127.0.0.1:${SIGNALFORGE_MODEL_PORT:-8000}/metrics" > "$prefix-metrics-before.prom"
  "$benchmark_bin" \
    --base-url "http://127.0.0.1:${SIGNALFORGE_MODEL_PORT:-8000}/v1" \
    --model signalforge-gemma4-26b-q4 \
    --cases "$repo_root/fixtures/model-baseline-cases.json" \
    --warmup-repetitions 1 \
    --repetitions 5 \
    --concurrency "$concurrency" \
    --output "$prefix.json" &
  local benchmark_pid="$!"
  python3 "$repo_root/scripts/capture_rocm_telemetry.py" \
    --output "$prefix-telemetry.jsonl" \
    --watch-pid "$benchmark_pid" \
    --process-root-pid "$server_pid" \
    --duration 900 \
    --interval 1 &
  local telemetry_pid="$!"
  wait "$benchmark_pid"
  wait "$telemetry_pid" || true
  curl -fsS "http://127.0.0.1:${SIGNALFORGE_MODEL_PORT:-8000}/metrics" > "$prefix-metrics-after.prom"
  python3 "$repo_root/scripts/summarize_benchmark.py" "$prefix.json" --output "$prefix-summary.json"
  python3 "$repo_root/scripts/summarize_rocm_telemetry.py" \
    "$prefix-telemetry.jsonl" --output "$prefix-telemetry-summary.json"
  python3 "$repo_root/scripts/summarize_llama_metrics.py" \
    "$prefix-metrics-before.prom" "$prefix-metrics-after.prom" \
    --output "$prefix-native-metrics.json"
}

run_measurement single 1
run_measurement contention 4

PROFILE_ID="$profile_id" OUTPUT_DIR="$output_dir" python3 - <<'PY'
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

directory = Path(os.environ["OUTPUT_DIR"])
single = json.loads((directory / "single-summary.json").read_text())
contention = json.loads((directory / "contention-summary.json").read_text())
single_rows = json.loads((directory / "single.json").read_text())["observations"]
contention_rows = json.loads((directory / "contention.json").read_text())["observations"]
single_failures = [row for row in single_rows if not row["row"]["success"]]
transport_failures = [row for row in contention_rows if row.get("error")]
truncation_failures = [
    row for row in contention_rows
    if not row["row"]["success"] and row.get("finish_reason") == "length" and not row.get("error")
]
other_contention_failures = [
    row for row in contention_rows
    if not row["row"]["success"] and row not in transport_failures and row not in truncation_failures
]
quality_passed = (
    not single_failures
    and not transport_failures
    and len(truncation_failures) <= 2
    and not other_contention_failures
    and contention["overall"]["success_rate"] >= 0.95
)
manifest = {
    "schema_version": "signalforge/radeon-optimization-run/v1",
    "profile_id": os.environ["PROFILE_ID"],
    "measured_at": datetime.now(timezone.utc).isoformat(),
    "runtime": {
        "context_size": int(os.environ.get("SIGNALFORGE_CONTEXT_SIZE", "32768")),
        "parallel_slots": int(os.environ.get("SIGNALFORGE_PARALLEL_SLOTS", "4")),
        "batch_size": int(os.environ.get("SIGNALFORGE_BATCH_SIZE", "2048")),
        "ubatch_size": int(os.environ.get("SIGNALFORGE_UBATCH_SIZE", "512")),
        "flash_attention": os.environ.get("SIGNALFORGE_FLASH_ATTN", "auto"),
        "cache_type_k": os.environ.get("SIGNALFORGE_CACHE_TYPE_K", "f16"),
        "cache_type_v": os.environ.get("SIGNALFORGE_CACHE_TYPE_V", "f16"),
        "continuous_batching": os.environ.get("SIGNALFORGE_CONT_BATCHING", "1") != "0",
        "unified_kv_cache": os.environ.get("SIGNALFORGE_KV_UNIFIED", "1") != "0",
    },
    "startup_ready_ms": int((directory / "startup-ready-ms.txt").read_text()),
    "quality_gate": {
        "passed": quality_passed,
        "single_failures": len(single_failures),
        "transport_failures": len(transport_failures),
        "bounded_output_truncations": len(truncation_failures),
        "other_contention_failures": len(other_contention_failures),
        "observations": single["overall"]["observations"] + contention["overall"]["observations"],
    },
    "single_summary_sha256": hashlib.sha256((directory / "single-summary.json").read_bytes()).hexdigest(),
    "contention_summary_sha256": hashlib.sha256((directory / "contention-summary.json").read_bytes()).hexdigest(),
}
(directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
if not quality_passed:
    raise SystemExit("frozen quality gate failed; see manifest.json")
PY

trap - EXIT
echo "Radeon profile completed: $profile_id"
