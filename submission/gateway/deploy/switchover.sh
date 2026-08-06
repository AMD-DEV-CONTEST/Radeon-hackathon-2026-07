#!/usr/bin/env bash
# switchover.sh — Stop Python orchestrator, build and start Go orchestrator
# Run as root on JD-ECS (111.228.42.18)
# Usage: cd /root/unionagents-go && bash deploy/switchover.sh

set -euo pipefail

REPO=/root/unionagents-go
LOG=/root/switchover-$(date +%Y%m%d-%H%M%S).log
exec > >(tee -a "$LOG") 2>&1

echo "=== UnionAgents Go Switchover — $(date) ==="

# ── 1. Detect and stop Python orchestrator ───────────────────────────────
echo ""
echo "[1/6] Stopping Python orchestrator..."

PY_UNIT=""
for unit in unionagents ua-orchestrator unionagents-py orchestrator; do
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        PY_UNIT="$unit"
        break
    fi
done

if [ -n "$PY_UNIT" ]; then
    echo "  Found systemd unit: $PY_UNIT — stopping..."
    systemctl stop "$PY_UNIT"
    # Disable auto-restart so it stays stopped
    systemctl disable "$PY_UNIT" || true
    echo "  Stopped and disabled: $PY_UNIT"
else
    # Try killing by port 8000 if no systemd unit found
    PY_PID=$(lsof -ti:8000 2>/dev/null || true)
    if [ -n "$PY_PID" ]; then
        echo "  No systemd unit found. Killing PID $PY_PID on port 8000..."
        kill "$PY_PID"
        sleep 2
    else
        echo "  WARNING: nothing found on port 8000. Proceeding."
    fi
fi

# ── 2. Git pull go-migration branch ──────────────────────────────────────
echo ""
echo "[2/6] Git pull go-migration..."
cd "$REPO"
git fetch origin
git checkout go-migration
git pull origin go-migration
echo "  HEAD: $(git log -1 --format='%h %s')"

# ── 3. Build Go binaries ──────────────────────────────────────────────────
echo ""
echo "[3/6] Building Go binaries..."
mkdir -p bin
go build -o bin/orchestrator ./cmd/orchestrator
go build -o bin/ils ./cmd/ils
go build -o bin/gateway ./cmd/gateway
echo "  Binaries:"
ls -lh bin/orchestrator bin/ils bin/gateway

# ── 4. Check/create .env ──────────────────────────────────────────────────
echo ""
echo "[4/6] Checking .env..."
if [ ! -f "$REPO/.env" ]; then
    echo "  WARNING: .env not found! Copying from template..."
    cp "$REPO/deploy/env-template" "$REPO/.env"
    echo "  IMPORTANT: Edit /root/unionagents-go/.env and set DB_PASSWORD, AUTH_SECRET, AUTH_PASSWORD"
    echo "  Then restart: systemctl restart ua-orchestrator"
fi

# Validate critical env vars
source "$REPO/.env" 2>/dev/null || true
if [ -z "${DB_PASSWORD:-}" ]; then
    echo "  ERROR: DB_PASSWORD is not set in .env. Aborting."
    exit 1
fi
echo "  .env OK (DB_PASSWORD set)"

# ── 5. Install and start Go orchestrator service ──────────────────────────
echo ""
echo "[5/6] Installing systemd service..."
cp "$REPO/deploy/ua-orchestrator.service" /etc/systemd/system/ua-orchestrator.service
systemctl daemon-reload
systemctl enable ua-orchestrator
systemctl start ua-orchestrator
echo "  ua-orchestrator started."

# ── 6. Smoke test ─────────────────────────────────────────────────────────
echo ""
echo "[6/6] Smoke test..."
sleep 2
HEALTH=$(curl -s --max-time 5 http://localhost:8000/health 2>&1)
echo "  /health: $HEALTH"

if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo ""
    echo "=== SWITCHOVER COMPLETE ==="
    echo "Go orchestrator is live at :8000"
    STATS=$(curl -s --max-time 5 http://localhost:8000/tasks/stats 2>&1)
    echo "  /tasks/stats: $STATS"
    echo "  Log saved to: $LOG"
else
    echo ""
    echo "=== SWITCHOVER FAILED — health check did not return ok ==="
    echo "  Check logs: journalctl -u ua-orchestrator -n 50"
    echo "  Full log: $LOG"
    exit 1
fi
