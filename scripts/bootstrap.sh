#!/usr/bin/env bash
# bootstrap.sh — Start llama-server + download model (optional rc-tunnel exposure)
#
# Usage:
#   bash scripts/bootstrap.sh                  # Start llama-server only (local access)
#   EXPOSE_LLM_PORT=1 bash scripts/bootstrap.sh  # Also expose port 8080 via rc-tunnel
#
# Location: /workspace/bootstrap.sh or scripts/bootstrap.sh
set -uo pipefail
LOG=/workspace/bootstrap.log
exec > >(tee -a "$LOG") 2>&1
echo "===== bootstrap $(date) ====="

# SSH public key and API key are injected via environment variables (never hardcode):
#   export SSH_PUBKEY="ssh-ed25519 AAAA... you@host"
#   export LLAMA_API_KEY="your-key"
SSH_PUBKEY="${SSH_PUBKEY:-}"
MODEL_PATH=/workspace/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf
MODEL_REPO=Jackrong/Qwopus3.6-27B-v2-MTP-GGUF
MODEL_FILE=Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf
LLAMA_DIR=/opt/llama.cpp
PORT=8080
API_KEY="${LLAMA_API_KEY:-}"
TUNNEL_URL_FILE=/workspace/tunnel_url.txt

# 1. SSH (retained: for emergency debugging, not the primary access channel)
echo "[1/5] Installing SSH (for emergency debugging)..."
if ! command -v sshd >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y openssh-server
fi
mkdir -p /run/sshd /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
if [ -n "$SSH_PUBKEY" ]; then
  grep -qF "$SSH_PUBKEY" /root/.ssh/authorized_keys 2>/dev/null || echo "$SSH_PUBKEY" >> /root/.ssh/authorized_keys
else
  echo "  [INFO] SSH_PUBKEY env var not set, skipping public key injection"
fi
chmod 600 /root/.ssh/authorized_keys
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
pgrep -x sshd >/dev/null 2>&1 || /usr/sbin/sshd
echo "  sshd: $(pgrep -x sshd >/dev/null 2>&1 && echo OK || echo FAIL)"

# 2. modelscope
echo "[2/5] Installing modelscope..."
python3 -c "import modelscope" 2>/dev/null || pip3 install -U modelscope --break-system-packages -q
echo "  modelscope: $(python3 -c 'import modelscope;print(modelscope.__version__)' 2>/dev/null || echo FAIL)"

# 3. Model
echo "[3/5] Checking model..."
if [ -f "$MODEL_PATH" ]; then
  echo "  Already exists: $(ls -lh "$MODEL_PATH" | awk '{print $5}')"
else
  echo "  Downloading $MODEL_FILE ..."
  modelscope download --model "$MODEL_REPO" --local_dir /workspace "$MODEL_FILE" \
    && echo "  Download complete: $(ls -lh "$MODEL_PATH" | awk '{print $5}')" \
    || echo "  [WARN] Download failed"
fi

# 4. llama-server (bind to 127.0.0.1, rc-tunnel only supports 127.0.0.1)
echo "[4/5] Starting llama-server..."
if pgrep -f "llama-server" >/dev/null 2>&1; then
  echo "  Already running"
else
  if [ -f "$MODEL_PATH" ] && [ -x "$LLAMA_DIR/llama-server" ]; then
    cd "$LLAMA_DIR"
    # Public exposure must enable authentication (rc-tunnel docs: "your app must enforce login or authentication")
    if [ -z "$API_KEY" ]; then
      echo "  [WARN] LLAMA_API_KEY not set, public exposure will have no auth! Please set env var and retry"
      API_KEY_ARG=""
    else
      API_KEY_ARG="--api-key $API_KEY"
    fi
    HIP_VISIBLE_DEVICES=0 nohup ./llama-server \
      -m "$MODEL_PATH" -c 131072 -ngl 999 \
      -ctk q8_0 -ctv q8_0 -fa on --jinja --spec-type draft-mtp --spec-draft-n-max 1 \
      -t 16 -b 512 -ub 512 -np 1 \
      --host 127.0.0.1 --port "$PORT" $API_KEY_ARG \
      > /workspace/llama-server.log 2>&1 &
    echo "  Starting (PID $!), log at /workspace/llama-server.log"
    echo "  Waiting for llama-server to be ready..."
    for i in $(seq 1 30); do
      if curl -sf --connect-timeout 2 http://127.0.0.1:"$PORT"/v1/models >/dev/null 2>&1; then
        echo "  llama-server ready (${i}s)"
        break
      fi
      sleep 1
    done
  else
    echo "  [WARN] Model or binary missing, skipping"
  fi
fi

# 5. rc-tunnel public exposure (optional, disabled by default)
# setup-cloud.sh handles exposing port 8000 (web console) separately, no need to expose 8080 (LLM)
# Only expose LLM port when EXPOSE_LLM_PORT=1 (legacy: remote inference mode)
EXPOSE_LLM_PORT="${EXPOSE_LLM_PORT:-0}"
if [ "$EXPOSE_LLM_PORT" != "1" ]; then
  echo "[5/5] rc-tunnel: skipped (EXPOSE_LLM_PORT not set, setup-cloud.sh will expose port 8000)"
else
echo "[5/5] rc-tunnel public exposure (LLM :8080)..."
RC_TUNNEL="$HOME/.local/bin/rc-tunnel"

# Install rc-tunnel (idempotent)
if [ ! -x "$RC_TUNNEL" ]; then
  echo "  Installing rc-tunnel..."
  if [ -f /var/run/secrets/frp-self-service/install ]; then
    /var/run/secrets/frp-self-service/install 2>&1 || echo "  [WARN] rc-tunnel installation failed"
  else
    echo "  [ERROR] /var/run/secrets/frp-self-service/install not found"
    echo "  May be an old Pod, need to recreate Notebook and retry"
  fi
fi

# Stop old tunnel if any
if [ -x "$RC_TUNNEL" ]; then
  "$RC_TUNNEL" stop >/dev/null 2>&1 || true
  sleep 2

  # Expose port and get public URL
  echo "  Exposing port $PORT..."
  TUNNEL_OUTPUT=$("$RC_TUNNEL" expose --port "$PORT" 2>&1)
  echo "  $TUNNEL_OUTPUT"

  # Extract public URL (format: https://rc-xxx.radeon.firstdg.ai)
  TUNNEL_URL=$(echo "$TUNNEL_OUTPUT" | grep -oE 'https://rc-[a-z0-9]+\.radeon\.firstdg\.ai' | head -1)

  if [ -n "$TUNNEL_URL" ]; then
    # Save to file for local access
    echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
    echo ""
    echo "  ============================================"
    echo "  Public URL: $TUNNEL_URL"
    echo "  Saved to: $TUNNEL_URL_FILE"
    echo "  ============================================"
    echo ""
    echo "  Local config:"
    echo "    export LLM_BASE_URL=\"${TUNNEL_URL}/v1\""
    echo "    export LLM_API_KEY=\"$API_KEY\""
    echo ""
    # Verify public reachability (wait a few seconds for FRP to establish connection)
    echo "  Verifying public connectivity (waiting 5s)..."
    sleep 5
    if curl -sf --connect-timeout 10 -m 15 \
         -H "Authorization: Bearer $API_KEY" \
         "$TUNNEL_URL/v1/models" >/dev/null 2>&1; then
      echo "  Public verification: OK"
    else
      echo "  Public verification: not ready yet, may need more time (FRP connecting)"
      echo "  Manual verify: curl -H 'Authorization: Bearer $API_KEY' $TUNNEL_URL/v1/models"
    fi
  else
    echo "  [WARN] Failed to extract public URL, check output above"
    echo "  Troubleshoot: $RC_TUNNEL status ; $RC_TUNNEL logs --lines 50"
  fi
else
  echo "  [WARN] rc-tunnel not installed, skipping public exposure"
  echo "  Manual install: /var/run/secrets/frp-self-service/install"
fi
fi  # end EXPOSE_LLM_PORT check

echo "===== Status ====="
echo "  sshd:$(pgrep -x sshd >/dev/null 2>&1 && echo ON || echo OFF) llama:$(pgrep -f llama-server >/dev/null 2>&1 && echo ON || echo OFF) tunnel:$([ -f "$TUNNEL_URL_FILE" ] && echo "$(cat "$TUNNEL_URL_FILE")" || echo OFF)"
echo "===== done ====="
