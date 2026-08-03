#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-10.0.0.201}"
MODEL="${MODEL:-/codebase/models/Qwen2.5-Coder-14B-Instruct-abliterated-Q6_K.gguf}"
PROFILE="${2:-tp2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STARTER="${SCRIPT_DIR}/start_remote_llama_worker.sh"

if [[ ! -x "${STARTER}" ]]; then
  echo "Starter script missing or not executable: ${STARTER}"
  exit 1
fi

case "${PROFILE}" in
  tp2)
    "${STARTER}" "${HOST}" "${MODEL}" 5200 "0,1" "50,50" 8192 8 99
    "${STARTER}" "${HOST}" "${MODEL}" 5201 "2,3" "50,50" 8192 8 99
    ;;
  tp3)
    "${STARTER}" "${HOST}" "${MODEL}" 5200 "0,1,2" "34,33,33" 8192 8 99
    ;;
  tp4)
    "${STARTER}" "${HOST}" "${MODEL}" 5200 "0,1,2,3" "25,25,25,25" 8192 8 99
    ;;
  *)
    echo "Unknown profile: ${PROFILE} (use tp2|tp3|tp4)"
    exit 1
    ;;
esac

echo "[profile] ${PROFILE} launched on ${HOST}"
