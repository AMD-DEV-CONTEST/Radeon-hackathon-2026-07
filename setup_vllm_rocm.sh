#!/usr/bin/env bash
set -euo pipefail

# AMD Radeon / ROCm vLLM launcher for the hackathon.
# Default path uses the official ROCm vLLM OpenAI-compatible Docker image.
# Use MODE=pip for an explicit ROCm PyTorch + vLLM wheel installation.

MODEL_ID="${MODEL_ID:-Qwen/Qwen2-7B-Instruct}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
MODE="${MODE:-docker}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
VLLM_ROCM_IMAGE_TAG="${VLLM_ROCM_IMAGE_TAG:-latest}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

print_startup_banner() {
  cat <<EOF
Starting vLLM ROCm server
  mode:       ${MODE}
  model:      ${MODEL_ID}
  endpoint:   http://${HOST}:${PORT}/v1
  max length: ${MAX_MODEL_LEN}
  gpu memory: ${GPU_MEMORY_UTILIZATION}
EOF
}

run_with_docker() {
  require_command docker
  mkdir -p "${HF_HOME}"

  docker pull "vllm/vllm-openai-rocm:${VLLM_ROCM_IMAGE_TAG}"

  exec docker run --rm \
    --name async-code-optimizer-vllm \
    --group-add=video \
    --cap-add=SYS_PTRACE \
    --security-opt seccomp=unconfined \
    --device /dev/kfd \
    --device /dev/dri \
    --network=host \
    --ipc=host \
    -v "${HF_HOME}:/root/.cache/huggingface" \
    -e "HF_TOKEN=${HF_TOKEN:-}" \
    "vllm/vllm-openai-rocm:${VLLM_ROCM_IMAGE_TAG}" \
    --model "${MODEL_ID}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --dtype auto \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --trust-remote-code
}

detect_gfx_target() {
  if [[ -n "${GFX_TARGET:-}" ]]; then
    echo "${GFX_TARGET}"
    return
  fi

  if command -v rocminfo >/dev/null 2>&1; then
    local detected
    detected="$(rocminfo | grep -oE 'gfx[0-9a-f]+' | head -n 1 || true)"
    if [[ -n "${detected}" ]]; then
      echo "${detected}"
      return
    fi
  fi

  echo "gfx1200"
}

run_with_pip() {
  require_command python3.14

  local gfx_target
  gfx_target="$(detect_gfx_target)"
  local gpu_family="${GPU_FAMILY:-rdna}"

  python3.14 -m venv .venv-vllm-rocm
  # shellcheck disable=SC1091
  source .venv-vllm-rocm/bin/activate
  python -m pip install --upgrade pip uv

  python -m pip install --index-url https://repo.amd.com/rocm/whl-multi-arch/ \
    "torch[device-${gfx_target}]==2.11.0+rocm7.14.0" \
    "torchvision[device-${gfx_target}]==0.26.0+rocm7.14.0" \
    "torchaudio==2.11.0+rocm7.14.0"

  if [[ "${gpu_family}" == "cdna" ]]; then
    python -m pip install \
      "https://rocm.frameworks.amd.com/whl-multi-arch/vllm-cdna/flash-attn/flash_attn-2.8.3-cp314-cp314-linux_x86_64.whl"
    python -m pip install \
      "https://rocm.frameworks.amd.com/whl-multi-arch/vllm-cdna/amd-aiter/amd_aiter-0.1.13.post2.dev1%2Bgb32deb267-cp314-cp314-linux_x86_64.whl"
    uv pip install \
      "https://rocm.frameworks.amd.com/whl-multi-arch/vllm-cdna/vllm/vllm-0.23.1.dev1%2Brocm7.14.0.g9ddef7117.d20260715-cp314-cp314-linux_x86_64.whl"
  else
    python -m pip install \
      "https://rocm.frameworks.amd.com/whl-multi-arch/vllm-rdna/flash-attn/flash_attn-2.8.3-py3-none-any.whl"
    uv pip install \
      "https://rocm.frameworks.amd.com/whl-multi-arch/vllm-rdna/vllm/vllm-0.23.1.dev1%2Brocm7.14.0.g9ddef7117.d20260715-cp314-cp314-linux_x86_64.whl"
  fi

  export PYTHONPATH="$VIRTUAL_ENV/lib/python3.14/site-packages/_rocm_sdk_core/share/amd_smi:${PYTHONPATH:-}"
  export FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE

  python -c "import vllm; print('vLLM version:', vllm.__version__)"
  python -c "import torch; print('PyTorch:', torch.__version__); print('HIP available:', torch.cuda.is_available())"
  python -c "import flash_attn; print('flash-attn:', flash_attn.__version__)"

  exec vllm serve "${MODEL_ID}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --dtype auto \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --trust-remote-code
}

print_startup_banner

case "${MODE}" in
  docker)
    run_with_docker
    ;;
  pip)
    run_with_pip
    ;;
  *)
    echo "Unsupported MODE=${MODE}. Use MODE=docker or MODE=pip." >&2
    exit 1
    ;;
esac
