#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

mkdir -p artifacts/e2e var

if [[ "${POLICYSEAL_E2E_EXTERNAL:-0}" == "1" ]]; then
  exec pnpm --filter @policyseal/web exec playwright test "$@"
fi

if [[ "${POLICYSEAL_E2E_SKIP_BROWSER_INSTALL:-0}" != "1" ]]; then
  pnpm --filter @policyseal/web exec playwright install chromium
fi

run_dir="$(mktemp -d "${repo_root}/var/policyseal-e2e.XXXXXX")"
api_log="${run_dir}/api.log"
web_log="${run_dir}/web.log"
api_pid=""
web_pid=""

cleanup() {
  local status=$?
  if [[ -n "${web_pid}" ]]; then kill "${web_pid}" 2>/dev/null || true; fi
  if [[ -n "${api_pid}" ]]; then kill "${api_pid}" 2>/dev/null || true; fi
  wait "${web_pid}" 2>/dev/null || true
  wait "${api_pid}" 2>/dev/null || true
  if [[ ${status} -ne 0 ]]; then
    printf '\n--- PolicySeal E2E API log ---\n' >&2
    tail -n 120 "${api_log}" >&2 || true
    printf '\n--- PolicySeal E2E web log ---\n' >&2
    tail -n 120 "${web_log}" >&2 || true
  fi
  rm -rf "${run_dir}"
  exit "${status}"
}
trap cleanup EXIT INT TERM

port_open() {
  "${repo_root}/.venv/bin/python" -c \
    'import socket, sys; sock = socket.socket(); sock.settimeout(0.2); sys.exit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' \
    "$1"
}

if port_open 5173 || port_open 8787; then
  printf 'PolicySeal E2E requires free localhost ports 5173 and 8787.\n' >&2
  exit 1
fi

export POLICYSEAL_ENVIRONMENT="e2e"
export POLICYSEAL_DATABASE_URL="sqlite:///${run_dir}/policyseal.db"
export POLICYSEAL_POLICY_DIR="${repo_root}/policies"
export POLICYSEAL_DATA_DIR="${run_dir}"
export POLICYSEAL_STORAGE_DIR="${run_dir}/files"
export POLICYSEAL_MASTER_KEY_PATH="${run_dir}/secrets/master.key"
export POLICYSEAL_EMBEDDING_CACHE_DIR="${run_dir}/cache/fastembed"
export POLICYSEAL_EMBEDDING_LOCAL_FILES_ONLY="true"
export POLICYSEAL_CORS_ORIGINS='["http://127.0.0.1:5173"]'

"${repo_root}/.venv/bin/uvicorn" policyseal.api.app:app \
  --app-dir "${repo_root}/src" \
  --host 127.0.0.1 \
  --port 8787 >"${api_log}" 2>&1 &
api_pid=$!

pnpm --filter @policyseal/web exec vite \
  --host 127.0.0.1 \
  --port 5173 \
  --strictPort >"${web_log}" 2>&1 &
web_pid=$!

for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8787/api/health >/dev/null \
    && curl -fsS http://127.0.0.1:5173/ >/dev/null; then
    break
  fi
  if ! kill -0 "${api_pid}" 2>/dev/null || ! kill -0 "${web_pid}" 2>/dev/null; then
    printf 'A PolicySeal E2E service exited during startup.\n' >&2
    exit 1
  fi
  sleep 0.25
done

curl -fsS http://127.0.0.1:8787/api/health >/dev/null
curl -fsS http://127.0.0.1:5173/ >/dev/null

pnpm --filter @policyseal/web exec playwright test "$@"
