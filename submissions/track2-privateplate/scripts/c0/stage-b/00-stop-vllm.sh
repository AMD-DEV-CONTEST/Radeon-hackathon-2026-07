#!/usr/bin/env bash
# Always-safe stop for the formal C0-B vLLM process of the current run.
# Safe to call when no server is running. Does not touch protected evidence dirs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "${PRIVATEPLATE_RUN_ID:-}" && -z "${PRIVATEPLATE_C0B_OUT_DIR:-}" ]]; then
  echo "00-stop-vllm: no run id/out dir; nothing to stop for a formal run."
  exit 0
fi

OUT_DIR="${PRIVATEPLATE_C0B_OUT_DIR:-${ROOT}/benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}}"
RAW_DIR="${OUT_DIR}/raw"
PID_FILE="${RAW_DIR}/vllm-server.pid"
STOP_LOG="${RAW_DIR}/vllm-stop.json"
HOST="${PRIVATEPLATE_VLLM_HOST:-127.0.0.1}"
PORT="${PRIVATEPLATE_VLLM_PORT:-8000}"

mkdir -p "${RAW_DIR}" 2>/dev/null || true

stopped_pid=""
stop_method="none"
process_alive_before=false
process_alive_after=false
port_open_after=false

if [[ -f "${PID_FILE}" ]]; then
  pid="$(tr -d '[:space:]' <"${PID_FILE}" || true)"
  if [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]]; then
    if kill -0 "${pid}" 2>/dev/null; then
      process_alive_before=true
      stopped_pid="${pid}"
      kill "${pid}" 2>/dev/null || true
      # Grace period then SIGKILL if needed.
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        if ! kill -0 "${pid}" 2>/dev/null; then
          break
        fi
        sleep 1
      done
      if kill -0 "${pid}" 2>/dev/null; then
        kill -9 "${pid}" 2>/dev/null || true
        stop_method="sigkill"
      else
        stop_method="sigterm"
      fi
    else
      stop_method="pid_file_stale"
      stopped_pid="${pid}"
    fi
  fi
fi

# Best-effort: free the formal bind port if something still listens (same host only).
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -qE "[\\.:]${PORT}\\s"; then
    port_open_after=true
  fi
elif command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    port_open_after=true
  fi
fi

if [[ -n "${stopped_pid}" ]] && kill -0 "${stopped_pid}" 2>/dev/null; then
  process_alive_after=true
else
  process_alive_after=false
fi

node -e '
  const fs = require("node:fs");
  const payload = {
    schema_version: "1.0",
    stage: "C0-B",
    phase: "TEARDOWN",
    stopped_at_utc: new Date().toISOString(),
    host: process.argv[1],
    port: Number(process.argv[2]),
    pid: process.argv[3] ? Number(process.argv[3]) : null,
    process_alive_before: process.argv[4] === "true",
    process_alive_after: process.argv[5] === "true",
    port_open_after: process.argv[6] === "true",
    stop_method: process.argv[7],
    lifecycle_note:
      "This receipt records only the local vLLM service stop."
  };
  fs.writeFileSync(process.argv[8], JSON.stringify(payload, null, 2) + "\n");
  console.log(JSON.stringify({ status: payload.process_alive_after ? "WARN_STILL_ALIVE" : "STOPPED", ...payload }, null, 2));
' \
  "${HOST}" \
  "${PORT}" \
  "${stopped_pid}" \
  "${process_alive_before}" \
  "${process_alive_after}" \
  "${port_open_after}" \
  "${stop_method}" \
  "${STOP_LOG}"

if [[ "${process_alive_after}" == "true" ]]; then
  echo "00-stop-vllm: FAIL process still alive after stop attempts." >&2
  exit 2
fi

# Port still listening is a hard failure when we expected a formal stop.
if [[ "${port_open_after}" == "true" && "${process_alive_before}" == "true" ]]; then
  echo "00-stop-vllm: FAIL port ${PORT} still open after stop." >&2
  exit 2
fi
if [[ "${port_open_after}" == "true" && -f "${PID_FILE}" ]]; then
  echo "00-stop-vllm: FAIL port ${PORT} still open (stale or foreign listener)." >&2
  exit 2
fi

echo "00-stop-vllm: done (method=${stop_method})"
exit 0
