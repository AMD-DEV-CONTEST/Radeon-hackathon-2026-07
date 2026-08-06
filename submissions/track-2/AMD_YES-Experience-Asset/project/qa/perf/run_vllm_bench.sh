#!/usr/bin/env bash
# Run on Radeon Cloud. A missing server/tool is a failure; no placeholder
# manifest is produced. Copy manifest.template.json only after a real run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${QA_BASE_URL:-http://127.0.0.1:8000/v1}"
MODEL="${QA_MODEL:?set QA_MODEL to the exact served model id}"
LABEL="${1:?usage: run_vllm_bench.sh <label> [output-dir]}"
OUT="${2:-$ROOT/../benchmarks/runs/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL}"
CONCURRENCY="${CONCURRENCY:-1}"
NUM_PROMPTS="${NUM_PROMPTS:-50}"

command -v vllm >/dev/null || { echo "FAIL: vllm is not installed in this environment" >&2; exit 1; }
command -v curl >/dev/null || { echo "FAIL: curl is required" >&2; exit 1; }
curl --fail --silent --show-error "${BASE_URL%/v1}/health" >/dev/null || {
  echo "FAIL: vLLM health endpoint is unavailable at ${BASE_URL%/v1}/health" >&2
  exit 1
}

mkdir -p "$OUT"
{
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'base_url=%s\nmodel=%s\nconcurrency=%s\nnum_prompts=%s\n' \
    "$BASE_URL" "$MODEL" "$CONCURRENCY" "$NUM_PROMPTS"
} >"$OUT/command.env"

python3 "$ROOT/scripts/capture_vram.py" \
  --duration "${VRAM_SAMPLE_SECONDS:-120}" \
  --interval "${VRAM_SAMPLE_INTERVAL:-1}" \
  --output "$OUT/vram.csv" &
SAMPLER_PID=$!
trap 'kill "$SAMPLER_PID" 2>/dev/null || true' EXIT

vllm bench serve \
  --base-url "${BASE_URL%/v1}" \
  --model "$MODEL" \
  --dataset-name random \
  --num-prompts "$NUM_PROMPTS" \
  --max-concurrency "$CONCURRENCY" \
  --save-result \
  --result-dir "$OUT"

if ! kill -0 "$SAMPLER_PID" 2>/dev/null; then
  wait "$SAMPLER_PID" || true
  echo "FAIL: AMD-SMI sampler stopped before the benchmark completed" >&2
  exit 1
fi
kill "$SAMPLER_PID" 2>/dev/null || true
wait "$SAMPLER_PID" 2>/dev/null || true
trap - EXIT

echo "PASS: raw vLLM and VRAM results retained at $OUT"
echo "NEXT: copy qa/perf/manifest.template.json into this directory, fill it from real evidence, then validate it."
