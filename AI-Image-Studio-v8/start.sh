#!/bin/bash
# AI-Image-Studio v8 — one-command public start on the Radeon Cloud instance.
# Kills the old app, restarts rc-tunnel, auto-detects the fresh tunnel URL,
# applies the ImageEditor light-frame patch, then launches with APP_PUBLIC_URL.
cd /workspace/persistent/AI-Image-Studio-v8
[ -f /workspace/persistent/env.sh ] && source /workspace/persistent/env.sh
# Keep MIOpen's autotune database on the persistent disk — otherwise every
# instance restart wipes it and the first run at each shape stalls ~6 min
# re-compiling convolution kernels.
export MIOPEN_USER_DB_PATH="${MIOPEN_USER_DB_PATH:-/workspace/persistent/miopen-db}"
mkdir -p "$MIOPEN_USER_DB_PATH"
# All models are pre-downloaded into the HF cache, but a hung hub metadata
# check (no connect timeout) once froze the app for 25 min during warmup.
# Short timeouts make the hub fail fast and fall back to the local cache.
# (Full HF_HUB_OFFLINE=1 is NOT used: offline mode requires an explicit
# weight_name for load_lora_weights and would break LCM turbo.)
export HF_HUB_ETAG_TIMEOUT=3
export HF_HUB_DOWNLOAD_TIMEOUT=15
pkill -f "app.py"; sleep 2
~/.local/bin/rc-tunnel stop 2>/dev/null; sleep 1
URL=$(~/.local/bin/rc-tunnel expose --port 7860 2>&1 | grep -o 'https://[^ ]*' | head -1)
echo "Tunnel: $URL"
python scripts/patch_editor_frame.py
APP_PUBLIC_URL="$URL" nohup python -u app.py > app.log 2>&1 &
sleep 15 && curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:7860/
