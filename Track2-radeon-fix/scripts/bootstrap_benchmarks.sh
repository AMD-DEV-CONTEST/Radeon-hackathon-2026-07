#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCHMARK_DIR="${ROOT_DIR}/benchmarks"
mkdir -p "${BENCHMARK_DIR}"

clone_at() {
  local url="$1"
  local destination="$2"
  local revision="$3"
  if [[ ! -d "${destination}/.git" ]]; then
    git clone --filter=blob:none "${url}" "${destination}"
  fi
  git -C "${destination}" fetch --depth 1 origin "${revision}"
  git -C "${destination}" checkout --detach "${revision}"
}

clone_at https://github.com/Aider-AI/aider.git \
  "${BENCHMARK_DIR}/aider" 5dc9490bb35f9729ef2c95d00a19ccd30c26339c
clone_at https://github.com/ozyyshr/RepoGraph.git \
  "${BENCHMARK_DIR}/RepoGraph" 6c3977d87845993bf2c0359b4ac752278d7f3c45
clone_at https://github.com/SWE-bench/SWE-bench.git \
  "${BENCHMARK_DIR}/SWE-bench" f7bbbb2ccdf479001d6467c9e34af59e44a840f9

mkdir -p "${BENCHMARK_DIR}/qwen-code"
npm install --prefix "${BENCHMARK_DIR}/qwen-code" \
  --save-exact @qwen-code/qwen-code@0.21.0

echo "Pinned benchmark dependencies are ready in ${BENCHMARK_DIR}."
