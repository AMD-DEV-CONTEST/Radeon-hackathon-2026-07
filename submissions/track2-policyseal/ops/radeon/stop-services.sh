#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_root"

session="${POLICYSEAL_TMUX_SESSION:-policyseal}"
runtime_dir="${project_root}/var/radeon"
keep_vllm="false"
if [[ "${1:-}" == "--keep-vllm" ]]; then
  keep_vllm="true"
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--keep-vllm]" >&2
  exit 2
fi

kill_window() {
  local name="$1"
  if tmux list-windows -t "$session" -F '#{window_name}' 2>/dev/null | grep -Fxq "$name"; then
    tmux kill-window -t "${session}:${name}"
  fi
  rm -f "${runtime_dir}/${name}.pid"
}

kill_window api
kill_window web
if [[ "$keep_vllm" == "false" ]]; then
  kill_window vllm
fi

if tmux has-session -t "$session" 2>/dev/null; then
  remaining="$(tmux list-windows -t "$session" -F '#{window_name}')"
  if [[ -z "$remaining" ]]; then
    tmux kill-session -t "$session"
  fi
fi

printf 'PolicySeal services stopped%s.\n' "$([[ "$keep_vllm" == "true" ]] && printf '; vLLM kept running')"
