#!/usr/bin/env bash
# Radeon Cloud: expose PrivateLocalAgent web UI with official rc-tunnel.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${HTTP_PORT:-7900}"

echo "[1] install rc-tunnel (official)"
if [[ -x /var/run/secrets/frp-self-service/install ]]; then
  /var/run/secrets/frp-self-service/install || true
fi
export PATH="$HOME/.local/bin:$PATH"
command -v rc-tunnel >/dev/null || { echo "rc-tunnel missing — recreate Notebook if install failed"; exit 1; }
rc-tunnel version || true

echo "[2] ensure web on 127.0.0.1:${PORT}"
if ! curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
  export PLA_ALLOW_PUBLIC=1 HTTP_HOST=127.0.0.1 HTTP_PORT="$PORT" PLA_OPEN_BROWSER=0
  export PLA_DATA_ROOT="${PLA_DATA_ROOT:-/workspace/persistence/PrivateLocalAgent}"
  export HF_HOME="${HF_HOME:-/workspace/persistence/huggingface}"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
  nohup python scripts/web_http_demo.py > /tmp/pla_web.log 2>&1 &
  for i in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break
    sleep 2
  done
fi
curl -fsS "http://127.0.0.1:${PORT}/healthz"
echo

echo "[3] expose with rc-tunnel"
rc-tunnel stop >/dev/null 2>&1 || true
rc-tunnel expose --port "$PORT" | tee /tmp/pla_rc_tunnel.log
echo
echo "Public URL:"
grep -oE 'https://[^ ]+radeon\.firstdg\.ai[^ ]*' /tmp/pla_rc_tunnel.log | tail -n 1 || true
