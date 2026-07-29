#!/usr/bin/env bash
# Start Doubao web UI + cloudflared for Notebook/external use (Radeon Cloud).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export GIT_SSL_NO_VERIFY="${GIT_SSL_NO_VERIFY:-true}"
export PLA_ALLOW_PUBLIC=1
export HTTP_HOST=127.0.0.1
export HTTP_PORT="${HTTP_PORT:-7900}"
export PLA_OPEN_BROWSER=0

mkdir -p .tools
if [[ ! -x .tools/cloudflared ]]; then
  if [[ -x notebooks/.tools/cloudflared ]]; then
    mv -f notebooks/.tools/cloudflared .tools/cloudflared
  else
    echo "[ui] downloading cloudflared..."
    curl -kfsSL -o .tools/cloudflared \
      https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x .tools/cloudflared
  fi
fi
./.tools/cloudflared version

# Stop old listeners on port if any
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${HTTP_PORT}/tcp" 2>/dev/null || true
fi

echo "[ui] starting web on http://127.0.0.1:${HTTP_PORT}"
python scripts/web_http_demo.py > /tmp/pla_web.log 2>&1 &
WEB_PID=$!
sleep 2
if ! kill -0 "$WEB_PID" 2>/dev/null; then
  echo "[ui] web failed; see /tmp/pla_web.log"
  tail -n 50 /tmp/pla_web.log || true
  exit 1
fi

echo "[ui] starting cloudflared tunnel..."
./.tools/cloudflared tunnel --url "http://127.0.0.1:${HTTP_PORT}" 2>&1 | tee /tmp/pla_tunnel.log &
TUN_PID=$!

URL=""
for i in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/pla_tunnel.log | tail -n 1 || true)
  if [[ -n "$URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$URL" ]]; then
  echo "[ui] tunnel URL not ready yet. Watch: tail -f /tmp/pla_tunnel.log"
  echo "[ui] web pid=$WEB_PID tunnel pid=$TUN_PID"
  exit 2
fi

echo ""
echo "========================================"
echo "打开这个网址（Notebook外/内都可用）："
echo "$URL"
echo "========================================"
echo "web_pid=$WEB_PID tunnel_pid=$TUN_PID"
echo "$URL" > /tmp/pla_public_url.txt
