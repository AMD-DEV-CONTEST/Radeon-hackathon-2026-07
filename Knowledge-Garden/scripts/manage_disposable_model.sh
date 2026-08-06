#!/bin/bash
# manage_disposable_model.sh — stop/start the DISPOSABLE model endpoint (Todo 11).
#
# Used by the Todo 11 failure case (stopped-endpoint) to stop and restart the
# disposable model endpoint inside the bootstrap stack.
#
# Usage:
#   bash scripts/manage_disposable_model.sh --port <p> --action stop|start \
#       [--health-timeout <s>] [--model-dir <dir>] [--served-name <name>]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT=""
ACTION=""
HEALTH_TIMEOUT=120
MODEL_DIR="${LC_DISPOSABLE_MODEL_DIR:-/persistent/models/Qwen2.5-14B-Instruct}"
SERVED_NAME="${LC_DISPOSABLE_MODEL_NAME:-Qwen2.5-14B-Instruct}"
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2;;
    --action) ACTION="$2"; shift 2;;
    --health-timeout) HEALTH_TIMEOUT="$2"; shift 2;;
    --model-dir) MODEL_DIR="$2"; shift 2;;
    --served-name) SERVED_NAME="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$PORT" ] && [ -n "$ACTION" ] || { echo "manage_disposable_model: --port and --action required" >&2; exit 2; }
case "$ACTION" in stop|start) ;; *) echo "action must be stop|start" >&2; exit 2;; esac

PID="$(bash "$ROOT/scripts/find_listener_pid.sh" "$PORT" 2>/dev/null || true)"
case "$ACTION" in
  stop)
    if [ -n "$PID" ]; then
      kill "$PID" 2>/dev/null || kill -9 "$PID" 2>/dev/null || true
      for i in $(seq 1 30); do
        bash "$ROOT/scripts/find_listener_pid.sh" "$PORT" >/dev/null 2>&1 || break
        sleep 1
      done
    fi
    if bash "$ROOT/scripts/find_listener_pid.sh" "$PORT" >/dev/null 2>&1; then
      echo "MANAGE_MODEL_STOP_FAIL: still listening on :$PORT" >&2
      exit 1
    fi
    echo "MANAGE_MODEL_STOP_OK: :$PORT stopped"
    ;;
  start)
    [ -d "$MODEL_DIR" ] || { echo "MANAGE_MODEL_START_FAIL: model dir $MODEL_DIR missing" >&2; exit 1; }
    setsid env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_ENDPOINT=https://hf-mirror.com \
      /opt/venv/bin/python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_DIR" --served-model-name "$SERVED_NAME" \
        --host 0.0.0.0 --port "$PORT" \
        --max-model-len 4096 --gpu-memory-utilization 0.5 --enforce-eager \
      > "/tmp/lc-disposable-${PORT}.log" 2>&1 < /dev/null &
    for i in $(seq 1 "$HEALTH_TIMEOUT"); do
      curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1 && break
      sleep 1
    done
    curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1 \
      || { echo "MANAGE_MODEL_START_FAIL: not healthy on :$PORT" >&2; exit 1; }
    echo "MANAGE_MODEL_START_OK: $SERVED_NAME on :$PORT"
    ;;
esac
exit 0
