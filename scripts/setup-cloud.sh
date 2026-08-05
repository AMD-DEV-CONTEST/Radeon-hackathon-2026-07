#!/usr/bin/env bash
# setup-cloud.sh — AMD Cloud one-click deployment script
#
# Usage: bash scripts/setup-cloud.sh
#
# Interactive cluster mode selection:
#   1) Local single-node — Direct Hadoop install on AMD Cloud host (no Docker, no HA)
#   2) Remote HA cluster — Connect to remote Docker 3-node Hadoop HA (requires remote SSH)
#
# Common steps (both modes):
#   1. Compile llama.cpp (ROCm)
#   2. Download model + start llama-server (bootstrap.sh)
#   3. Install Python dependencies
#   4. Build frontend
#   5. Start Agent + Web
#   6. rc-tunnel public exposure
set -euo pipefail

# ============================================================
# Configuration
# ============================================================
export LLAMA_API_KEY="${LLAMA_API_KEY:-aiops-$(date +%s)}"
export LLM_API_KEY="$LLAMA_API_KEY"
export LLM_MODEL="${LLM_MODEL:-/workspace/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf}"
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:8080/v1}"
export AUTONOMY="${AUTONOMY:-autonomous}"
export PROMPT_LANGUAGE="${PROMPT_LANGUAGE:-en}"
export CLUSTER_BACKEND="${CLUSTER_BACKEND:-apache}"
export DB_PATH="${DB_PATH:-/workspace/aiops.db}"

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ_DIR"

LOG_FILE="/workspace/setup-cloud.log"
exec > >(tee -a "$LOG_FILE") 2>&1
echo ""
echo "############################################################"
echo "#  AIOps Agent — AMD Cloud One-Click Deployment"
echo "#  Time: $(date)"
echo "#  Project: $PROJ_DIR"
echo "############################################################"
echo ""

# ============================================================
# Interactive cluster mode selection
# ============================================================
echo "Select Hadoop cluster mode:"
echo "  1) Local single-node — Direct Hadoop install on AMD Cloud host (no Docker, no HA)"
echo "  2) Remote HA cluster — Connect to remote Docker 3-node Hadoop HA"
echo ""
read -p "Enter 1 or 2 [default 1]: " CLUSTER_MODE
CLUSTER_MODE="${CLUSTER_MODE:-1}"
echo ""

if [ "$CLUSTER_MODE" = "1" ]; then
  echo "  Selected: Local single-node direct install"
else
  REMOTE_HOST="8.148.228.51"
  REMOTE_PORT="22"
  NODE01_PORT="2222"
  NODE02_PORT="2223"
  NODE03_PORT="2224"
  echo "  Selected: Remote HA cluster ($REMOTE_HOST)"
  echo ""
fi

# ============================================================
# Step 1: Compile llama.cpp (ROCm)
# ============================================================
echo "===== Step 1/6: Compile llama.cpp (ROCm) ====="
LLAMA_DIR="/opt/llama.cpp"
if [ -x "$LLAMA_DIR/llama-server" ]; then
  echo "  Already compiled, skipping"
else
  bash scripts/build-llama.sh
fi

# ============================================================
# Step 2: Model download + start llama-server (bootstrap.sh)
# ============================================================
echo ""
echo "===== Step 2/6: Model download + start llama-server ====="
bash scripts/bootstrap.sh

# After bootstrap.sh, detect the actual API key from the running llama-server.
# This prevents key mismatch when llama-server was already running from a previous
# bootstrap (bootstrap.sh skips restart if already running, but we generated a new key).
ACTUAL_API_KEY=$(pgrep -af llama-server 2>/dev/null | grep -oP '(?<=--api-key )\S+' | head -1 || true)
if [ -n "$ACTUAL_API_KEY" ]; then
  export LLAMA_API_KEY="$ACTUAL_API_KEY"
  export LLM_API_KEY="$ACTUAL_API_KEY"
fi

# ============================================================
# Step 3: Hadoop cluster setup
# ============================================================
echo ""
echo "===== Step 3/6: Hadoop cluster ====="
if [ "$CLUSTER_MODE" = "1" ]; then
  echo "  [Local single-node] Direct install Hadoop + ZK + HBase + Hive + Tez + MySQL + supervisord ..."
  bash scripts/setup-hadoop-direct.sh
else
  echo "  [Remote HA cluster] Testing connectivity to $REMOTE_HOST ..."
  echo ""

  SSH_BASE="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no"
  SSH_KEY="$PROJ_DIR/deploy/config/ssh/id_rsa"
  chmod 600 "$SSH_KEY" 2>/dev/null || true
  [ -f "$SSH_KEY" ] && SSH_BASE="$SSH_BASE -i $SSH_KEY"

  # Test each Hadoop node SSH (Docker containers via mapped ports)
  NODE_PORTS=($NODE01_PORT $NODE02_PORT $NODE03_PORT)
  NODE_NAMES=(hadoop01 hadoop02 hadoop03)
  for i in 0 1 2; do
    echo -n "  [$((i+1))/5] ${NODE_NAMES[$i]} SSH ($REMOTE_HOST:${NODE_PORTS[$i]})... "
    if ssh $SSH_BASE -p "${NODE_PORTS[$i]}" "root@$REMOTE_HOST" "hostname" 2>/dev/null | grep -q "${NODE_NAMES[$i]}"; then
      echo "OK"
    else
      echo "FAIL"
      echo "  [ERROR] Cannot SSH to ${NODE_NAMES[$i]} at $REMOTE_HOST:${NODE_PORTS[$i]}"
      exit 1
    fi
  done

  # Test supervisorctl on hadoop01 (quick health check)
  echo -n "  [4/5] Supervisor status (hadoop01)... "
  SUP_OUT=$(ssh $SSH_BASE -p "$NODE01_PORT" "root@$REMOTE_HOST" \
    "supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf status 2>&1" 2>/dev/null || true)
  if echo "$SUP_OUT" | grep -qE 'RUNNING|STOPPED|FATAL'; then
    RUNNING=$(echo "$SUP_OUT" | grep -c RUNNING || true)
    TOTAL=$(echo "$SUP_OUT" | grep -cE 'RUNNING|STOPPED|FATAL|STARTING' || true)
    echo "OK ($RUNNING/$TOTAL services RUNNING)"
  else
    echo "WARN (supervisorctl not available, will proceed)"
  fi

  # Test Prometheus connectivity
  echo -n "  [5/5] Prometheus ($REMOTE_HOST:9090)... "
  if curl -sf --connect-timeout 5 "http://$REMOTE_HOST:9090/-/healthy" >/dev/null 2>&1; then
    echo "OK"
  else
    echo "WARN (Prometheus not reachable, alert detection may be limited)"
  fi

  echo ""
  echo "  Remote cluster connectivity: OK"
fi

# ============================================================
# Step 4: Install Python dependencies
# ============================================================
echo ""
echo "===== Step 4/6: Install Python dependencies ====="
pip3 install -r requirements.txt --break-system-packages -q 2>&1 | tail -3

# Ensure setuptools <80: supervisorctl 4.2.5 depends on pkg_resources (removed in setuptools 80+)
# torch/modelscope may have pulled in a newer setuptools; downgrade if needed
if ! python3 -c "import pkg_resources" 2>/dev/null; then
  echo "  [FIX] pkg_resources missing (setuptools too new), pinning setuptools<80..."
  pip3 install --break-system-packages 'setuptools>=68,<80' -q 2>&1 | tail -1
fi

# ============================================================
# Step 5: Build frontend + generate config + start Agent
# ============================================================
echo ""
echo "===== Step 5/6: Build frontend + start Agent ====="

# Build frontend
if [ -f "$PROJ_DIR/web/dist/index.html" ]; then
  echo "  Frontend already built, skipping"
else
  bash scripts/build-frontend.sh
fi

# Generate secrets_local.py (both modes auto-generated)
SSH_KEY_PATH="$PROJ_DIR/deploy/config/ssh/id_rsa"
chmod 600 "$SSH_KEY_PATH" 2>/dev/null || true

if [ "$CLUSTER_MODE" = "1" ]; then
  cat > "$PROJ_DIR/src/secrets_local.py" << EOF
"""Auto-generated by setup-cloud.sh (single-node mode)"""
import os
os.environ.setdefault("CLUSTER_BACKEND", "$CLUSTER_BACKEND")
os.environ.setdefault("AUTONOMY", "$AUTONOMY")
os.environ.setdefault("PROMPT_LANGUAGE", "$PROMPT_LANGUAGE")
os.environ.setdefault("LLM_BASE_URL", "$LLM_BASE_URL")
os.environ.setdefault("LLM_API_KEY", "$LLAMA_API_KEY")
os.environ.setdefault("LLM_MODEL", "$LLM_MODEL")
os.environ.setdefault("DB_PATH", "$DB_PATH")
os.environ.setdefault("SSH_USER", "root")
os.environ.setdefault("SSH_KEY_PATH", "$SSH_KEY_PATH")
os.environ.setdefault("NODE01_HOST", "localhost")
os.environ.setdefault("NODE01_NAME", "hadoop01")
os.environ.setdefault("NODE01_SSH_PORT", "22")
os.environ.setdefault("PROMETHEUS_URL", "http://localhost:9090")
os.environ.setdefault("ALERTMANAGER_URL", "http://localhost:9093")
os.environ.setdefault("GRAFANA_URL", "http://localhost:3000")
EOF
  echo "  secrets_local.py generated (single-node)"
else
  cat > "$PROJ_DIR/src/secrets_local.py" << EOF
"""Auto-generated by setup-cloud.sh (remote HA cluster mode)"""
import os
os.environ.setdefault("CLUSTER_BACKEND", "$CLUSTER_BACKEND")
os.environ.setdefault("AUTONOMY", "$AUTONOMY")
os.environ.setdefault("PROMPT_LANGUAGE", "$PROMPT_LANGUAGE")
os.environ.setdefault("LLM_BASE_URL", "$LLM_BASE_URL")
os.environ.setdefault("LLM_API_KEY", "$LLAMA_API_KEY")
os.environ.setdefault("LLM_MODEL", "$LLM_MODEL")
os.environ.setdefault("DB_PATH", "$DB_PATH")
os.environ.setdefault("SSH_USER", "root")
os.environ.setdefault("SSH_KEY_PATH", "$SSH_KEY_PATH")
# Remote HA cluster: all nodes on $REMOTE_HOST with mapped SSH ports
os.environ.setdefault("NODE01_HOST", "$REMOTE_HOST")
os.environ.setdefault("NODE02_HOST", "$REMOTE_HOST")
os.environ.setdefault("NODE03_HOST", "$REMOTE_HOST")
os.environ.setdefault("NODE01_NAME", "hadoop01")
os.environ.setdefault("NODE02_NAME", "hadoop02")
os.environ.setdefault("NODE03_NAME", "hadoop03")
os.environ.setdefault("NODE01_SSH_PORT", "$NODE01_PORT")
os.environ.setdefault("NODE02_SSH_PORT", "$NODE02_PORT")
os.environ.setdefault("NODE03_SSH_PORT", "$NODE03_PORT")
# Monitoring endpoints on remote host
os.environ.setdefault("PROMETHEUS_URL", "http://$REMOTE_HOST:9090")
os.environ.setdefault("ALERTMANAGER_URL", "http://$REMOTE_HOST:9093")
os.environ.setdefault("GRAFANA_URL", "http://$REMOTE_HOST:3000")
EOF
  echo "  secrets_local.py generated (remote HA: $REMOTE_HOST)"
fi

# Stop old agent if running and wait for port to be released
pkill -f "python.*main.py" 2>/dev/null || true
for i in $(seq 1 10); do
  pgrep -f "python.*main.py" >/dev/null 2>&1 || break
  sleep 1
done
sleep 1  # extra wait for port release

# Start agent
echo "  Agent starting..."
cd "$PROJ_DIR"
nohup python3 -m main > /workspace/agent.log 2>&1 &
AGENT_PID=$!
echo "  Agent PID: $AGENT_PID"

# Wait for web to be ready
echo "  Waiting for web to be ready..."
for i in $(seq 1 30); do
  if curl -sf --connect-timeout 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "  Web ready (${i}s)"
    break
  fi
  sleep 1
done

# Health check
HEALTH=$(curl -sf http://127.0.0.1:8000/health 2>/dev/null || echo '{"status":"error"}')
echo "  Health check: $HEALTH"

# ============================================================
# Step 6: rc-tunnel public exposure
# ============================================================
echo ""
echo "===== Step 6/6: rc-tunnel public exposure ====="
RC_TUNNEL="$HOME/.local/bin/rc-tunnel"

# Install rc-tunnel (idempotent)
if [ ! -x "$RC_TUNNEL" ]; then
  echo "  rc-tunnel not found, installing..."
  if [ -f /var/run/secrets/frp-self-service/install ]; then
    /var/run/secrets/frp-self-service/install 2>&1
    # Re-check after install
    if [ ! -x "$RC_TUNNEL" ]; then
      # Maybe installed to a different path, try finding it
      RC_TUNNEL=$(which rc-tunnel 2>/dev/null || find /root/.local/bin /usr/local/bin /usr/bin -name rc-tunnel -type f 2>/dev/null | head -1)
    fi
  else
    echo "  [WARN] /var/run/secrets/frp-self-service/install not found"
    echo "  [INFO] May need to recreate Notebook to get rc-tunnel"
  fi
fi

if [ -x "$RC_TUNNEL" ]; then
  echo "  rc-tunnel found: $RC_TUNNEL"

  # Stop any existing tunnel first
  "$RC_TUNNEL" stop >/dev/null 2>&1 || true
  sleep 2

  # Expose port 8000
  echo "  Exposing port 8000..."
  TUNNEL_OUTPUT=$("$RC_TUNNEL" expose --port 8000 2>&1)

  # Extract public URL (format: https://rc-xxx.radeon.firstdg.ai)
  TUNNEL_URL=$(echo "$TUNNEL_OUTPUT" | grep -oE 'https://rc-[a-z0-9]+\.radeon\.firstdg\.ai' | head -1)

  if [ -n "$TUNNEL_URL" ]; then
    echo "$TUNNEL_URL" > /workspace/tunnel_url.txt

    # Verify connectivity (wait for FRP to establish)
    echo "  Verifying connectivity (waiting 5s)..."
    sleep 5
    if curl -sf --connect-timeout 10 -m 15 "$TUNNEL_URL/health" >/dev/null 2>&1; then
      echo "  Public access: OK"
    else
      echo "  [WARN] Not ready yet, FRP may still be connecting"
      echo "  Manual check: curl $TUNNEL_URL/health"
    fi
  else
    echo "  [WARN] Failed to extract public URL from output"
    echo "  Try manual: $RC_TUNNEL expose --port 8000"
    # Check tunnel status for debugging
    "$RC_TUNNEL" status 2>&1 || true
  fi
else
  echo "  [WARN] rc-tunnel not available"
  echo "  Local access only: http://127.0.0.1:8000"
fi

# ============================================================
# Complete
# ============================================================
# Read tunnel URL from file as fallback (variable may be out of scope)
if [ -z "${TUNNEL_URL:-}" ] && [ -f /workspace/tunnel_url.txt ]; then
  TUNNEL_URL=$(cat /workspace/tunnel_url.txt)
fi

echo ""
echo "############################################################"
echo "#  Deployment complete!"
echo "#"
if [ -n "${TUNNEL_URL:-}" ]; then
  echo "#  Public access: $TUNNEL_URL"
fi
echo "#  Login:         admin / admin"
echo "#  Agent log:     /workspace/agent.log"
echo "#  LLM log:       /workspace/llama-server.log"
echo "#"
echo "#  Run demo:      bash scripts/inject-fault.sh"
echo "############################################################"
echo ""
if [ -n "${TUNNEL_URL:-}" ]; then
  echo ">>> Open in browser: $TUNNEL_URL  (login: admin/admin)"
else
  echo ">>> Open in browser: http://127.0.0.1:8000  (login: admin/admin)"
fi
echo ""
