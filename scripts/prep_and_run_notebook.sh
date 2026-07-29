#!/usr/bin/env bash
# One-shot prep on Radeon Cloud before running the Notebook cell.
set -euo pipefail
cd /workspace/Radeon-hackathon-2026-07

export GIT_SSL_NO_VERIFY=true
git fetch origin track2-private-local-agent
git reset --hard origin/track2-private-local-agent

# stop old tunnel / web leftovers
export PATH="$HOME/.local/bin:$PATH"
if [[ -x /var/run/secrets/frp-self-service/install ]]; then
  /var/run/secrets/frp-self-service/install || true
fi
rc-tunnel stop >/dev/null 2>&1 || true
pkill -9 -f web_http_demo.py >/dev/null 2>&1 || true

echo "OK: code updated. Now open notebooks/visual_no_tunnel.ipynb"
echo "    Kernel → Restart Kernel → run the ONLY code cell."
