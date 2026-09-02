#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/scripts/lib/env.sh"
openalpha_load_env "$ROOT_DIR" runtime optional

OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/docs/submission/generated}"
MODEL_PATH="${MODEL_PATH:-}"
LLAMA_SOURCE="${LLAMA_SOURCE:-$ROOT_DIR/vendor/llama.cpp}"
LLAMA_BUILD="${LLAMA_BUILD:-$LLAMA_SOURCE/build}"
LLAMA_BENCH="${LLAMA_BENCH:-$LLAMA_BUILD/bin/llama-bench}"
LLAMA_GPU_LAYERS="${LLAMA_GPU_LAYERS:-99}"
BENCH_PROMPT_TOKENS="${BENCH_PROMPT_TOKENS:-512}"
BENCH_GENERATE_TOKENS="${BENCH_GENERATE_TOKENS:-256}"
BENCH_REPETITIONS="${BENCH_REPETITIONS:-5}"
BENCH_APP_ROUNDS="${BENCH_APP_ROUNDS:-5}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$OUTPUT_DIR/rocm-benchmark-$STAMP.txt"

mkdir -p "$OUTPUT_DIR"
if [[ -z "$MODEL_PATH" || ! -f "$MODEL_PATH" ]]; then
  echo "Set MODEL_PATH before collecting a ROCm benchmark." >&2
  exit 1
fi
if [[ ! -x "$LLAMA_BENCH" ]]; then
  echo "llama-bench is missing at $LLAMA_BENCH" >&2
  exit 1
fi
openalpha_require_commands rocminfo rocm-smi sha256sum tee

{
  echo "OpenAlpha Sentinel ROCm benchmark"
  echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "stamp=$STAMP"
  if [[ -f "$ROOT_DIR/.openalpha-deployment" ]]; then
    echo "--- deployment manifest ---"
    cat "$ROOT_DIR/.openalpha-deployment"
    sha256sum "$ROOT_DIR/.openalpha-deployment"
  else
    echo "deployment_manifest=missing"
  fi
  echo "--- operating system ---"
  if [[ -f /etc/os-release ]]; then cat /etc/os-release; fi
  uname -a
  "$ROOT_DIR/.venv/bin/python" --version
  if command -v hipcc >/dev/null 2>&1; then hipcc --version; fi
  if command -v amdclang++ >/dev/null 2>&1; then amdclang++ --version; fi
  echo "--- build provenance ---"
  if [[ -d "$LLAMA_SOURCE/.git" ]]; then
    printf 'llama_git_head=%s\n' "$(git -C "$LLAMA_SOURCE" rev-parse HEAD)"
    if [[ -n "$(git -C "$LLAMA_SOURCE" status --porcelain=v1 --untracked-files=all -- . ':(exclude)build' ':(exclude)build/**')" ]]; then
      echo "llama_git_state=dirty"
    else
      echo "llama_git_state=clean"
    fi
  else
    echo "llama_git_state=metadata-unavailable"
  fi
  sha256sum "$LLAMA_BENCH" "$ROOT_DIR/scripts/benchmark_rocm.sh" \
    "$ROOT_DIR/scripts/setup_rocm_llama.sh" "$MODEL_PATH"
  "$LLAMA_BENCH" --version || true
  if [[ -f "$LLAMA_BUILD/CMakeCache.txt" ]]; then
    grep -E '^(CMAKE_BUILD_TYPE|CMAKE_HIP_ARCHITECTURES|GGML_HIP|GGML_NATIVE):' \
      "$LLAMA_BUILD/CMakeCache.txt" || true
  fi
  echo "--- ROCm device inventory ---"
  rocminfo | sed -n '1,160p'
  rocm-smi --showproductname --showmeminfo vram --showuse --showtemp
  BENCH_COMMAND=("$LLAMA_BENCH" -m "$MODEL_PATH" -ngl "$LLAMA_GPU_LAYERS" \
    -p "$BENCH_PROMPT_TOKENS" -n "$BENCH_GENERATE_TOKENS" -r "$BENCH_REPETITIONS")
  printf 'llama_bench_command='
  printf ' %q' "${BENCH_COMMAND[@]}"
  printf '\n'
  "${BENCH_COMMAND[@]}"
  APP_COMMAND=("$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/benchmark_app.py" \
    --rounds "$BENCH_APP_ROUNDS")
  printf 'application_benchmark_command=OPENALPHA_LLM_BACKEND=llama_cpp'
  printf ' %q' "${APP_COMMAND[@]}"
  printf '\n'
  OPENALPHA_LLM_BACKEND=llama_cpp "${APP_COMMAND[@]}"
  echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} | tee "$REPORT"

echo "Benchmark evidence written to $REPORT"
