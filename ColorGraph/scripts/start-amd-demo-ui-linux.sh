#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
venv_path=${COLORGRAPH_ROCM_VENV:-"$repo_root/.venv-rocm"}
python="$venv_path/bin/python"
run_dir="$repo_root/.run"

if [[ ! -x "$python" ]]; then
    printf 'ROCm environment is missing: %s\n' "$venv_path" >&2
    printf 'Run scripts/setup-amd-demo-rocm-linux.sh first.\n' >&2
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    printf 'npm is required to serve the ColorGraph UI.\n' >&2
    exit 1
fi
if [[ ! -d "$repo_root/node_modules" ]]; then
    printf 'Frontend dependencies are missing; run npm ci in %s.\n' "$repo_root" >&2
    exit 1
fi

huggingface_redirect="$repo_root/backend/models/huggingface.redirect"
if [[ -n "${COLORGRAPH_HUGGINGFACE_CACHE_DIR:-}" ]]; then
    huggingface_cache=$COLORGRAPH_HUGGINGFACE_CACHE_DIR
elif [[ -f "$huggingface_redirect" ]]; then
    huggingface_cache=$(<"$huggingface_redirect")
else
    huggingface_cache="$repo_root/backend/models/huggingface"
fi
if [[ ! -d "$huggingface_cache" ]]; then
    printf 'Hugging Face cache is missing: %s\n' "$huggingface_cache" >&2
    exit 1
fi

export COLORGRAPH_DEVICE=${COLORGRAPH_DEVICE:-rocm}
export COLORGRAPH_HUGGINGFACE_CACHE_DIR="$huggingface_cache"
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE:-1}

mkdir -p "$run_dir"
backend_pid=
frontend_pid=

cleanup() {
    trap - EXIT INT TERM
    if [[ -n "$frontend_pid" ]]; then
        kill "$frontend_pid" 2>/dev/null || true
    fi
    if [[ -n "$backend_pid" ]]; then
        kill "$backend_pid" 2>/dev/null || true
    fi
    wait "$frontend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$repo_root"
"$python" -m uvicorn colorgraph.api.app:app \
    --host 127.0.0.1 \
    --port 8010 \
    >"$run_dir/amd-ui-backend.log" 2>&1 &
backend_pid=$!

npm run dev -- --host 127.0.0.1 --port 4173 \
    >"$run_dir/amd-ui-frontend.log" 2>&1 &
frontend_pid=$!

printf 'ColorGraph AMD demo services started on the server loopback interface.\n'
printf 'Backend PID: %s, log: %s\n' "$backend_pid" "$run_dir/amd-ui-backend.log"
printf 'Frontend PID: %s, log: %s\n' "$frontend_pid" "$run_dir/amd-ui-frontend.log"
printf 'From the recording workstation, open this tunnel:\n'
printf 'ssh -N -L 4173:127.0.0.1:4173 -L 8010:127.0.0.1:8010 USER@SERVER\n'
printf 'Then open http://127.0.0.1:4173 in the local browser.\n'

set +e
wait -n "$backend_pid" "$frontend_pid"
status=$?
set -e
exit "$status"
