#!/usr/bin/env bash
# Relaunch the self-optimized vLLM deployment with new server-side knobs.
# Usage: restart_vllm.sh <ATTENTION_BACKEND> <MAX_NUM_SEQS> <true|false prefix caching>
# Blocks until /v1/models answers. On failure, restores the last good config
# (state file) so the agent's brain always comes back. Exit codes:
#   0 = requested config live · 2 = requested config failed, previous restored
#   1 = nothing serving (fatal)
set -u

MODEL="${SERVE_MODEL:-google/gemma-4-31B-it-qat-w4a16-ct}"
PORT="${SERVE_PORT:-8000}"
STATE="${VLLM_STATE:-/workspace/vllm_state.json}"
LOG="${SERVE_LOG:-/workspace/vllm_serve.log}"
GPU_UTIL="${SERVE_GPU_UTIL:-0.90}"
# Tool calling for the agent loop. This build registers the Gemma parser as
# "functiongemma" (vllm/tool_parsers/__init__.py) and ships no gemma
# reasoning parser, so none is requested.
EXTRA="${SERVE_EXTRA_FLAGS:---enable-auto-tool-choice --tool-call-parser functiongemma}"
HEALTH_TRIES="${HEALTH_TRIES:-72}"   # x5s = 6 min ceiling per launch

BACKEND="${1:?attention backend}"; MNS="${2:?max_num_seqs}"; PC="${3:?prefix caching true|false}"

launch() {
  local backend=$1 mns=$2 pc=$3
  pkill -f 'vllm serv[e]' 2>/dev/null   # bracket: never match ourselves
  sleep 4
  local flags=(--host 0.0.0.0 --port "$PORT" --max-num-seqs "$mns"
               --gpu-memory-utilization "$GPU_UTIL")
  if [[ $pc == true ]]; then flags+=(--enable-prefix-caching)
  else flags+=(--no-enable-prefix-caching); fi
  echo "[restart_vllm] $(date +%T) launching backend=$backend mns=$mns prefix=$pc" >> "$LOG"
  # Offline load: all weights are pre-downloaded; the instance's egress has
  # proven flaky (Errno 101 mid-load killed a launch), so never touch the hub.
  VLLM_ATTENTION_BACKEND="$backend" FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    nohup /opt/venv/bin/vllm serve "$MODEL" "${flags[@]}" $EXTRA >> "$LOG" 2>&1 &
  local pid=$!
  for _ in $(seq 1 "$HEALTH_TRIES"); do
    sleep 5
    if curl -sf "http://localhost:$PORT/v1/models" >/dev/null; then return 0; fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "[restart_vllm] engine died during startup (backend=$backend)" >> "$LOG"
      return 1
    fi
  done
  echo "[restart_vllm] health check timed out (backend=$backend)" >> "$LOG"
  return 1
}

write_state() {
  printf '{"attention_backend":"%s","max_num_seqs":%s,"enable_prefix_caching":%s}\n' \
    "$1" "$2" "$3" > "$STATE"
}

if launch "$BACKEND" "$MNS" "$PC"; then
  write_state "$BACKEND" "$MNS" "$PC"
  exit 0
fi

echo "[restart_vllm] requested config failed; restoring last good config" >&2
if [[ -f $STATE ]]; then
  OB=$(python3 -c "import json;print(json.load(open('$STATE'))['attention_backend'])" 2>/dev/null)
  OM=$(python3 -c "import json;print(json.load(open('$STATE'))['max_num_seqs'])" 2>/dev/null)
  OP=$(python3 -c "import json;print(str(json.load(open('$STATE'))['enable_prefix_caching']).lower())" 2>/dev/null)
  if [[ -n ${OB:-} ]] && launch "$OB" "$OM" "$OP"; then
    exit 2
  fi
fi
exit 1
