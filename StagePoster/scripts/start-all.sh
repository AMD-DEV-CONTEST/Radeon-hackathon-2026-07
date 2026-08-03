#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_ROOT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
  pwd
)"

PROJECT_ROOT="$BACKEND_ROOT"
ENV_FILE="${ENV_FILE:-}"

# Support both backend/.env (legacy) and project root .env
if [[ -z "$ENV_FILE" ]]; then
  if [[ -f "$BACKEND_ROOT/.env" ]]; then
    ENV_FILE="$BACKEND_ROOT/.env"
  elif [[ -f "$PROJECT_ROOT/.env" ]]; then
    ENV_FILE="$PROJECT_ROOT/.env"
  else
    echo "Missing .env file. Looked in:" >&2
    echo "  $BACKEND_ROOT/.env" >&2
    echo "  $PROJECT_ROOT/.env" >&2
    echo "Copy .env.example to .env and edit it first." >&2
    exit 1
  fi
fi

set -a
source "$ENV_FILE"
set +a

ROOT="${STAGEPOSTER_ROOT:-/workspace/poster-engine}"
COMFY_ROOT="${COMFY_ROOT:-$ROOT/ComfyUI}"
COMFY_VENV="${COMFY_VENV:-$ROOT/venv}"
VLLM_VENV="${VLLM_VENV:-$ROOT/.venv-vllm}"

mkdir -p \
  /workspace/persistence/stageposter/data \
  /workspace/persistence/stageposter/storage/jobs \
  /workspace/persistence/stageposter/storage/assets \
  /workspace/persistence/stageposter/storage/posters \
  /workspace/persistence/stageposter/logs \
  /workspace/persistence/stageposter/run

pid_alive() {
  local file="$1"

  [[ -f "$file" ]] || return 1

  local pid
  pid="$(cat "$file")"

  kill -0 "$pid" 2>/dev/null
}

wait_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-120}"
  local auth="${4:-}"

  for _ in $(seq 1 "$attempts"); do
    if [[ -n "$auth" ]]; then
      if curl -fsS \
        -H "Authorization: Bearer $auth" \
        "$url" >/dev/null 2>&1; then
        echo "$name READY"
        return 0
      fi
    else
      if curl -fsS "$url" >/dev/null 2>&1; then
        echo "$name READY"
        return 0
      fi
    fi

    sleep 2
  done

  echo "$name failed to become ready: $url" >&2
  return 1
}

start_vllm() {
  local pid_file="$BACKEND_ROOT/run/vllm.pid"

  if pid_alive "$pid_file"; then
    echo "vLLM already running: PID $(cat "$pid_file")"
    return
  fi

  if [[ ! -x "$VLLM_VENV/bin/vllm" ]]; then
    echo "Missing vLLM executable: $VLLM_VENV/bin/vllm" >&2
    exit 1
  fi

  if [[ ! -d "$VLM_MODEL_PATH" ]]; then
    echo "Missing VLM model: $VLM_MODEL_PATH" >&2
    exit 1
  fi

  (
    cd "$ROOT"

    # mm-processor-cache-gb=0 关掉多模态预处理缓存。
    #
    # 默认 4GB 的那个缓存在这套 vLLM 上会把自己搞坏：跑过一段时间后，任何带图的
    # 请求都稳定 500，engine 日志是
    #   AssertionError: Expected a cached item for mm_hash=...
    # （vllm/multimodal/cache.py get_and_update_item）。纯文本请求不受影响，所以
    # 表现为"AI 会话一旦附了素材就必失败"。我们每次请求只送一张小图，重算的代价
    # 可以忽略，缓存带来的收益远不值这个稳定性代价。
    nohup env \
      VLLM_SERVER_DEV_MODE="${VLLM_SERVER_DEV_MODE:-1}" \
      VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE="${VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE:-256}" \
      "$VLLM_VENV/bin/vllm" serve "$VLM_MODEL_PATH" \
        --host "${VLM_HOST:-127.0.0.1}" \
        --port "${VLM_PORT:-8001}" \
        --served-model-name "${VLM_MODEL:-stageposter-vlm}" \
        --api-key "$VLM_API_KEY" \
        --dtype "${VLLM_DTYPE:-float16}" \
        --max-model-len "${VLLM_MAX_MODEL_LEN:-4096}" \
        --max-num-seqs "${VLLM_MAX_NUM_SEQS:-1}" \
        --max-num-batched-tokens "${VLLM_MAX_BATCHED_TOKENS:-4096}" \
        --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.65}" \
        --limit-mm-per-prompt '{"image":{"count":1,"width":768,"height":1152},"video":0}' \
        --mm-processor-cache-gb "${VLLM_MM_PROCESSOR_CACHE_GB:-0}" \
        --enforce-eager \
        --default-chat-template-kwargs '{"enable_thinking":false}' \
        --generation-config vllm \
        > "$BACKEND_ROOT/logs/vllm.log" 2>&1 &

    echo $! > "$pid_file"
  )

  wait_http \
    "VLM" \
    "${VLM_URL:-http://127.0.0.1:8001}/v1/models" \
    180 \
    "$VLM_API_KEY"

  # 不再请求睡眠。ROCm 7.2 + vLLM 0.20.0 上 --enable-sleep-mode 会让后续的
  # wake_up 死在 CUDA Error: invalid argument (cumem_allocator.cpp:187)，
  # 结果是所有 AI 接口在第一次调用之后全部 502。见 CLAUDE.md §7。
  # 代价是 vLLM 常驻显存；gpu-memory-utilization 0.65 给 ComfyUI 留出余量。
  echo "VLM resident (sleep mode disabled on ROCm)."
}

start_comfyui() {
  local pid_file="$BACKEND_ROOT/run/comfyui.pid"

  if pid_alive "$pid_file"; then
    echo "ComfyUI already running: PID $(cat "$pid_file")"
    return
  fi

  if [[ ! -x "$COMFY_VENV/bin/python" ]]; then
    echo "Missing ComfyUI Python: $COMFY_VENV/bin/python" >&2
    exit 1
  fi

  if [[ ! -f "$COMFY_ROOT/main.py" ]]; then
    echo "Missing ComfyUI: $COMFY_ROOT/main.py" >&2
    exit 1
  fi

  (
    cd "$COMFY_ROOT"

    nohup "$COMFY_VENV/bin/python" main.py \
      --listen "${COMFY_LISTEN:-127.0.0.1}" \
      --port "${COMFY_PORT:-8188}" \
      > "$BACKEND_ROOT/logs/comfyui.log" 2>&1 &

    echo $! > "$pid_file"
  )

  wait_http \
    "COMFYUI" \
    "${COMFY_URL:-http://127.0.0.1:8188}/system_stats" \
    180
}

start_backend() {
  local pid_file="$BACKEND_ROOT/run/backend.pid"
  local binary="$BACKEND_ROOT/poster-backend"

  if pid_alive "$pid_file"; then
    echo "Backend already running: PID $(cat "$pid_file")"
    return
  fi

  cd "$BACKEND_ROOT"

  go test ./...

  if ! go build -o "$binary" ./cmd/server; then
    echo "Build ./cmd/server failed." >&2
    echo "Check the actual backend main package path." >&2
    exit 1
  fi

  nohup "$binary" \
    > "$BACKEND_ROOT/logs/backend.log" 2>&1 &

  echo $! > "$pid_file"

  for _ in $(seq 1 60); do
    code="$(
      curl -sS \
        -o /dev/null \
        -w '%{http_code}' \
        "http://127.0.0.1:8080/api/ai/sessions/not-found" \
        || true
    )"

    if [[ "$code" == "404" ]]; then
      echo "BACKEND READY"
      return
    fi

    sleep 1
  done

  echo "Backend failed to become ready." >&2
  return 1
}

start_vllm
start_comfyui
start_backend

echo
echo "All StagePoster services are running."
echo "Run: $BACKEND_ROOT/scripts/status.sh"
