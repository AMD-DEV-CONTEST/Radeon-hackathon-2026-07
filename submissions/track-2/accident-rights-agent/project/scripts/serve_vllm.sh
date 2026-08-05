#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

primary_model_id="Qwen/Qwen3-VL-8B-Instruct"
fallback_model_id="Qwen/Qwen2.5-VL-7B-Instruct"
primary_model_path="/persistent/models/Qwen3-VL-8B-Instruct"
fallback_model_path="/persistent/models/Qwen2.5-VL-7B-Instruct"

model_id="${MODEL_ID:-$primary_model_path}"
served_model_name="${SERVED_MODEL_NAME:-}"
vllm_executable="${VLLM_EXECUTABLE:-/opt/venv/bin/vllm}"
vllm_host="${VLLM_HOST:-127.0.0.1}"
vllm_port="${VLLM_PORT:-8000}"
vllm_dtype="${VLLM_DTYPE:-auto}"
max_model_len="${VLLM_MAX_MODEL_LEN:-16384}"
gpu_memory_utilization="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
max_num_batched_tokens="${VLLM_MAX_NUM_BATCHED_TOKENS:-}"
max_images="${VLLM_MAX_IMAGES_PER_PROMPT:-8}"
prefix_caching="${ENABLE_PREFIX_CACHING:-0}"
flash_attention_triton_amd="${FLASH_ATTENTION_TRITON_AMD_ENABLE:-TRUE}"

case "$model_id" in
  "$primary_model_id")
    served_model_name="${served_model_name:-$primary_model_id}"
    ;;
  "$fallback_model_id")
    served_model_name="${served_model_name:-$fallback_model_id}"
    ;;
  "$primary_model_path")
    served_model_name="${served_model_name:-$primary_model_id}"
    ;;
  "$fallback_model_path")
    served_model_name="${served_model_name:-$fallback_model_id}"
    ;;
  *)
    echo "ERROR: MODEL_ID is outside the approved local model allow-list: $model_id" >&2
    exit 2
    ;;
esac

if [[ "$model_id" == /persistent/models/* ]]; then
  if [[ ! -f "$model_id/config.json" ]]; then
    echo "ERROR: approved local model is incomplete; config.json not found: $model_id" >&2
    exit 2
  fi
fi

if [[ "$vllm_host" != "127.0.0.1" ]]; then
  echo "ERROR: VLLM_HOST must be exactly 127.0.0.1; got $vllm_host" >&2
  exit 2
fi
if [[ "$vllm_port" != "8000" ]]; then
  echo "ERROR: VLLM_PORT must be exactly 8000; got $vllm_port" >&2
  exit 2
fi
if [[ "$flash_attention_triton_amd" != "TRUE" && "$flash_attention_triton_amd" != "FALSE" ]]; then
  echo "ERROR: FLASH_ATTENTION_TRITON_AMD_ENABLE must be TRUE or FALSE." >&2
  exit 2
fi
if [[ "$prefix_caching" != "0" && "$prefix_caching" != "1" ]]; then
  echo "ERROR: ENABLE_PREFIX_CACHING must be 0 or 1." >&2
  exit 2
fi
if [[ -n "$max_num_batched_tokens" && ! "$max_num_batched_tokens" =~ ^[0-9]+$ ]]; then
  echo "ERROR: VLLM_MAX_NUM_BATCHED_TOKENS must be a positive integer." >&2
  exit 2
fi
if [[ "$vllm_executable" == */* ]]; then
  if [[ ! -x "$vllm_executable" ]]; then
    echo "ERROR: vllm executable not found or not executable: $vllm_executable" >&2
    exit 127
  fi
elif ! command -v "$vllm_executable" >/dev/null 2>&1; then
  echo "ERROR: vllm executable not found: $vllm_executable" >&2
  echo "NEXT: capture the environment fingerprint, then install a ROCm-compatible vLLM build." >&2
  exit 127
fi

export FLASH_ATTENTION_TRITON_AMD_ENABLE="$flash_attention_triton_amd"

mkdir -p artifacts
log_path="${VLLM_LOG_PATH:-artifacts/vllm-$(date -u +%Y%m%dT%H%M%SZ).log}"
mkdir -p "$(dirname "$log_path")"
if [[ "${VLLM_TEE_LOG:-1}" == "1" ]]; then
  exec > >(tee -a "$log_path") 2>&1
else
  exec >>"$log_path" 2>&1
fi

command=(
  "$vllm_executable" serve "$model_id"
  --host "$vllm_host"
  --port "$vllm_port"
  --served-model-name "$served_model_name"
  --dtype "$vllm_dtype"
  --max-model-len "$max_model_len"
  --gpu-memory-utilization "$gpu_memory_utilization"
  --limit-mm-per-prompt "{\"image\": $max_images, \"video\": 0}"
)

if [[ "$prefix_caching" == "1" ]]; then
  command+=(--enable-prefix-caching)
else
  command+=(--no-enable-prefix-caching)
fi
if [[ -n "$max_num_batched_tokens" ]]; then
  command+=(--max-num-batched-tokens "$max_num_batched_tokens")
fi

printf 'STARTED_AT_UTC=%s\n' "$(date -u +%FT%TZ)"
printf 'MODEL_ID=%s\n' "$model_id"
printf 'LISTEN=http://%s:%s/v1\n' "$vllm_host" "$vllm_port"
printf 'PREFIX_CACHING=%s\n' "$prefix_caching"
printf 'MAX_MODEL_LEN=%s\n' "$max_model_len"
printf 'GPU_MEMORY_UTILIZATION=%s\n' "$gpu_memory_utilization"
printf 'MAX_NUM_BATCHED_TOKENS=%s\n' "${max_num_batched_tokens:-vllm-default}"
printf 'FLASH_ATTENTION_TRITON_AMD_ENABLE=%s\n' "$flash_attention_triton_amd"
printf 'LOG=%s\n' "$log_path"
printf 'COMMAND='
printf '%q ' "${command[@]}"
printf '\n'

exec "${command[@]}"
