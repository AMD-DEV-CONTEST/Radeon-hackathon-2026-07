#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "Usage: $0 <host> <model_path> <port> <gpu_ids_csv> [tensor_split_csv] [ctx] [threads] [ngl]"
  exit 1
fi

HOST="$1"
MODEL="$2"
PORT="$3"
GPU_IDS="$4"
TENSOR_SPLIT="${5:-}"
CTX="${6:-8192}"
THREADS="${7:-8}"
NGL="${8:-99}"
USER_NAME="${REMOTE_USER:-cesarops}"
BIN_PATH="${LLAMA_SERVER_BIN:-/home/cesarops/llama.cpp/build/bin/llama-server}"

IFS=',' read -r -a GPU_ARR <<< "${GPU_IDS}"
if [[ "${#GPU_ARR[@]}" -eq 0 ]]; then
  echo "gpu_ids_csv must include at least one GPU id (example: 0,1,2)"
  exit 1
fi

DEVICES=""
for gpu in "${GPU_ARR[@]}"; do
  gpu_trimmed="$(echo "$gpu" | xargs)"
  [[ -z "${gpu_trimmed}" ]] && continue
  if [[ -n "${DEVICES}" ]]; then
    DEVICES+=","
  fi
  DEVICES+="CUDA${gpu_trimmed}"
done

if [[ -z "${DEVICES}" ]]; then
  echo "No valid GPU IDs were parsed from: ${GPU_IDS}"
  exit 1
fi

if [[ -z "${TENSOR_SPLIT}" ]]; then
  count="${#GPU_ARR[@]}"
  base=$((100 / count))
  rem=$((100 - base * count))
  values=()
  for ((i=0; i<count; i++)); do
    v="${base}"
    if [[ "${i}" -eq 0 ]]; then
      v=$((v + rem))
    fi
    values+=("${v}")
  done
  TENSOR_SPLIT="$(IFS=, ; echo "${values[*]}")"
fi

REMOTE_CMD="setsid ${BIN_PATH} -m '${MODEL}' --host 0.0.0.0 --port ${PORT} -dev ${DEVICES} -sm layer -ts ${TENSOR_SPLIT} -ngl ${NGL} -c ${CTX} -t ${THREADS} > /tmp/llama_${PORT}.log 2>&1 < /dev/null & disown"

echo "[remote] ${USER_NAME}@${HOST} :: ${REMOTE_CMD}"
ssh -o BatchMode=yes -o ConnectTimeout=8 "${USER_NAME}@${HOST}" "bash -lc \"${REMOTE_CMD}\""
echo "[ok] started on http://${HOST}:${PORT}"
