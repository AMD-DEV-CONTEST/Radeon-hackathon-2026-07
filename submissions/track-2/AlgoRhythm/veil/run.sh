#!/usr/bin/env bash
# VEIL launcher. Three commands, in the order you will need them.
#
#   ./run.sh serve    start vLLM on the Radeon GPU (terminal 1)
#   ./run.sh app      start the VEIL app + tunnel (terminal 2)
#   ./run.sh bench    measure tokens/sec and prefix cache hit rate
#
# vLLM binds to loopback deliberately. rc-tunnel publishes exactly one port and
# it is the app's, so the model server is never reachable from outside the pod.

set -euo pipefail
cd "$(dirname "$0")"

MODEL="${VEIL_MODEL:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
PORT="${VEIL_PORT:-7860}"
GPU_UTIL="${VEIL_GPU_UTIL:-0.90}"
MAX_LEN="${VEIL_MAX_LEN:-16384}"

serve() {
  export HF_ENDPOINT=https://hf-mirror.com
  /opt/venv/bin/python -c "
path = '/opt/venv/lib/python3.10/site-packages/vllm/model_executor/layers/rotary_embedding/common.py'
content = open(path).read()
old = '        if find_spec(\"flash_attn\") is not None:\n            from flash_attn.ops.triton.rotary import apply_rotary\n\n            self.apply_rotary_emb_flash_attn = apply_rotary'
new = '        if find_spec(\"flash_attn\") is not None:\n            try:\n                from flash_attn.ops.triton.rotary import apply_rotary\n                self.apply_rotary_emb_flash_attn = apply_rotary\n            except (ImportError, ModuleNotFoundError):\n                self.apply_rotary_emb_flash_attn = None'
if old in content:
    open(path, 'w').write(content.replace(old, new))
"
  echo "Serving ${MODEL} (gpu-util ${GPU_UTIL}, max-len ${MAX_LEN})"
  echo "If this OOMs, walk the ladder in README §Fallback — in hour 1, not hour 20."
  # --dtype float16 is pinned: bf16 paths are numerically unreliable on RDNA.
  # --enable-prefix-caching is the whole concurrency design; without it the
  # five personas each pay full prefill for the same document.
  /opt/venv/bin/vllm serve "${MODEL}" \
    --host 127.0.0.1 --port 8000 \
    --quantization awq \
    --dtype float16 \
    --max-model-len "${MAX_LEN}" \
    --gpu-memory-utilization "${GPU_UTIL}" \
    --enable-prefix-caching \
    --max-num-seqs 16 \
    --disable-log-requests
}

app() {
  export HF_ENDPOINT=https://hf-mirror.com
  if [ ! -f "veil_state.db" ]; then
    echo "No corpus found — building it now."
    /persistent/veil-env/bin/python -m veil.ingest.corpus_builder corpus/meridian
  fi
  echo "Starting VEIL on port ${PORT}"
  /persistent/veil-env/bin/python -m veil.main &
  APP_PID=$!
  sleep 3
  echo "Exposing port ${PORT} via bore tunnel..."
  kill -9 $(pgrep -f "bore local") 2>/dev/null || true
  # Try stable port 48483 first.
  bore local "${PORT}" --to bore.pub --port 48483 > /root/bore.log 2>&1 &
  sleep 2
  if grep -q "port already in use" /root/bore.log; then
    echo "Port 48483 in use on bore.pub, requesting a dynamic port..."
    bore local "${PORT}" --to bore.pub > /root/bore.log 2>&1 &
    sleep 2
  fi
  BORE_PORT=$(grep -oE "listening at bore.pub:[0-9]+" /root/bore.log | grep -oE "[0-9]+" || echo "16094")
  echo "-> Bore URL: http://bore.pub:${BORE_PORT}"

  echo "Exposing port ${PORT} via localhost.run"
  kill -9 $(pgrep -f "nokey@localhost.run") 2>/dev/null || true
  ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R 80:localhost:${PORT} nokey@localhost.run > /root/tunnel.log 2>&1 &
  wait $APP_PID
}

bench() {
  export HF_ENDPOINT=https://hf-mirror.com
  export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}/persistent/VEIL-hackathon-submission/veil"
  /persistent/veil-env/bin/python -m bench.benchmark "$@"
}

build_frontend() {
  FRONTEND_DIR="$(dirname "$0")/frontend"
  if [ -d "$FRONTEND_DIR" ]; then
    echo "Building frontend…"
    (cd "$FRONTEND_DIR" && npm install --silent && npm run build)
    echo "Frontend built → veil/static/"
  else
    echo "No frontend/ directory found. Skipping."
  fi
}

case "${1:-app}" in
  serve)           serve ;;
  app)             app ;;
  build-frontend)  build_frontend ;;
  bench)           shift; bench "$@" ;;
  test)            /persistent/veil-env/bin/pytest -q ;;
  *)               echo "usage: ./run.sh {serve|app|build-frontend|bench|test}"; exit 1 ;;
esac
