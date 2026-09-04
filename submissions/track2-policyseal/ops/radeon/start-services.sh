#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_root"
source ops/radeon/policyseal-env.sh

runtime_dir="${project_root}/var/radeon"
session="${POLICYSEAL_TMUX_SESSION:-policyseal}"
mkdir -p "$runtime_dir"

if [[ ! -x .venv/bin/python ]]; then
  echo "Project environment is missing; run make bootstrap first." >&2
  exit 1
fi

.venv/bin/python ops/radeon/validate-runtime.py \
  --output "${runtime_dir}/runtime-validation.json"

healthy() {
  curl --fail --silent --show-error --max-time 3 "$1" >/dev/null 2>&1
}

window_exists() {
  tmux list-windows -t "$session" -F '#{window_name}' 2>/dev/null | grep -Fxq "$1"
}

start_window() {
  local name="$1"
  local command="$2"
  local health_url="$3"

  if window_exists "$name" && healthy "$health_url"; then
    tmux display-message -p -t "${session}:${name}" '#{pane_pid}' >"${runtime_dir}/${name}.pid"
    printf '%s is already healthy.\n' "$name"
    return
  fi
  if window_exists "$name"; then
    tmux kill-window -t "${session}:${name}"
  fi
  if ! tmux has-session -t "$session" 2>/dev/null; then
    tmux new-session -d -s "$session" -n "$name" -c "$project_root" "$command"
  else
    tmux new-window -d -t "$session" -n "$name" -c "$project_root" "$command"
  fi
  tmux display-message -p -t "${session}:${name}" '#{pane_pid}' >"${runtime_dir}/${name}.pid"
}

wait_healthy() {
  local name="$1"
  local url="$2"
  local timeout_seconds="$3"
  local started="$SECONDS"
  until healthy "$url"; do
    if (( SECONDS - started >= timeout_seconds )); then
      echo "${name} did not become healthy; inspect ${runtime_dir}/${name}.log." >&2
      exit 1
    fi
    sleep 2
  done
}

vllm_started="false"
if ! healthy http://127.0.0.1:8000/v1/models; then
  vllm_started="true"
fi
start_window vllm \
  "bash -lc 'source ops/radeon/policyseal-env.sh; exec ops/radeon/start-vllm.sh >>var/radeon/vllm.log 2>&1'" \
  http://127.0.0.1:8000/v1/models
vllm_start_ms="$(date +%s%3N)"
wait_healthy vllm http://127.0.0.1:8000/v1/models 600
if [[ "$vllm_started" == "true" ]]; then
  printf '%s\n' "$(( $(date +%s%3N) - vllm_start_ms ))" >"${runtime_dir}/vllm-startup-ms"
elif [[ ! -f "${runtime_dir}/vllm-startup-ms" ]]; then
  printf '0\n' >"${runtime_dir}/vllm-startup-ms"
fi

start_window api \
  "bash -lc 'source ops/radeon/policyseal-env.sh; exec .venv/bin/uvicorn policyseal.api.app:app --app-dir src --host 127.0.0.1 --port 8787 >>var/radeon/api.log 2>&1'" \
  http://127.0.0.1:8787/api/health
wait_healthy api http://127.0.0.1:8787/api/health 60

start_window web \
  "bash -lc 'source ops/radeon/policyseal-env.sh; exec pnpm --filter @policyseal/web dev --host 127.0.0.1 --port 5173 >>var/radeon/web.log 2>&1'" \
  http://127.0.0.1:5173/
wait_healthy web http://127.0.0.1:5173/ 60

ops/radeon/health-check.sh >/dev/null
printf 'PolicySeal is ready in tmux session %s.\n' "$session"
printf 'Web: http://127.0.0.1:5173  API: http://127.0.0.1:8787/api/health\n'
