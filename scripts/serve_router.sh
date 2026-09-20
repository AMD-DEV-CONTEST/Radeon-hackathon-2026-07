#!/bin/bash
# AutoQuant router launcher (port 8090). Reuses public_site venv (fastapi/httpx/uvicorn).
set -u
cd /workspace/public_site
set -a
. /workspace/public_site/.router.env
set +a
export ROUTER_DISABLED="${ROUTER_DISABLED:-0}"
nohup ./venv/bin/python -m uvicorn router:app --host 127.0.0.1 --port 8090 > router.log 2>&1 &
echo "router pid $! (ROUTER_DISABLED=$ROUTER_DISABLED) at $(date -u)"
