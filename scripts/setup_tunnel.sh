#!/bin/bash
# scripts/setup_tunnel.sh — competition tunnel config: expose frontend to the public internet
#
# Based on the AMD Radeon Cloud rc-tunnel tool:
#   https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
#
# Prerequisites:
#   1. A Notebook instance has been created on Radeon Cloud
#   2. The vLLM service is running on port 8000 (internal call, no need to expose)
#   3. The Agent frontend service is running on 127.0.0.1:8080
#
# Limitations:
#   - Each Notebook Pod can expose only one port at a time
#   - HTTP/WebSocket only, TCP/UDP/SSH not supported
#   - The service must listen on 127.0.0.1
#   - Port range 1024-65535, cannot be a platform-reserved port
#
# Usage:
#   bash scripts/setup_tunnel.sh install   # install rc-tunnel
#   bash scripts/setup_tunnel.sh expose     # expose port 8080
#   bash scripts/setup_tunnel.sh status     # view tunnel status
#   bash scripts/setup_tunnel.sh logs        # view tunnel logs
#   bash scripts/setup_tunnel.sh stop       # stop the tunnel
#
set -e

# ── configuration ──
EXPOSE_PORT="${TUNNEL_PORT:-8080}"
RC_TUNNEL="$HOME/.local/bin/rc-tunnel"

# color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "${BLUE}[STEP]${NC}  $1"; }

# ── install rc-tunnel ──
do_install() {
    step "Installing rc-tunnel tool..."

    if [ -f "$RC_TUNNEL" ]; then
        info "rc-tunnel already installed: $RC_TUNNEL"
        $RC_TUNNEL version 2>/dev/null || true
        return 0
    fi

    if [ ! -f "/var/run/secrets/frp-self-service/install" ]; then
        error "Install script not found: /var/run/secrets/frp-self-service/install"
        error "Your Notebook may be an old Pod; shut it down and recreate the Notebook on Radeon Cloud"
        exit 1
    fi

    /var/run/secrets/frp-self-service/install
    info "Installation complete: $RC_TUNNEL"

    # ensure PATH contains the install path
    export PATH="$HOME/.local/bin:$PATH"

    # verify the installation
    if $RC_TUNNEL version 2>/dev/null; then
        info "rc-tunnel version check passed"
    else
        warn "rc-tunnel version command failed, but the install script ran. Run 'rc-tunnel version' in a new terminal to verify"
    fi
}

# ── check the local service ──
check_local_service() {
    step "Checking the local service 127.0.0.1:${EXPOSE_PORT}..."

    if ! curl --fail --silent --max-time 3 "http://127.0.0.1:${EXPOSE_PORT}/" > /dev/null 2>&1; then
        warn "The local service 127.0.0.1:${EXPOSE_PORT} is not responding"
        warn "Please start the Agent frontend service first:"
        echo ""
        echo "  cd \$(find / -name 'insurance-rag-agent' -type d 2>/dev/null | head -1)"
        echo "  python scripts/start_server.py"
        echo ""
        warn "Or, if the service is bound to 0.0.0.0, restart it with --host 127.0.0.1:"
        echo ""
        echo "  python scripts/start_server.py --host 127.0.0.1 --port 8080"
        echo ""
        read -p "Service started? Press Enter to continue, or Ctrl+C to exit..."
    else
        info "The local service 127.0.0.1:${EXPOSE_PORT} is responding normally"
    fi
}

# ── expose the port ──
do_expose() {
    check_local_service

    step "Exposing port ${EXPOSE_PORT} to the public internet..."

    if [ ! -f "$RC_TUNNEL" ]; then
        error "rc-tunnel is not installed; first run: bash scripts/setup_tunnel.sh install"
        exit 1
    fi

    # check whether a tunnel is already running
    EXISTING_STATUS=$("$RC_TUNNEL" status 2>&1 || true)
    if echo "$EXISTING_STATUS" | grep -q "running" 2>/dev/null; then
        warn "Detected an existing running tunnel:"
        echo "$EXISTING_STATUS"
        echo ""
        warn "Each Notebook can expose only one port at a time."
        read -p "Stop the existing tunnel and re-expose? (y/N): " CONFIRM
        if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
            info "Keeping the existing tunnel, exiting"
            exit 0
        fi
        "$RC_TUNNEL" stop
        info "Existing tunnel stopped"
        sleep 2
    fi

    # expose the port
    info "Requesting a public domain and establishing the tunnel..."
    "$RC_TUNNEL" expose --port "$EXPOSE_PORT"

    echo ""
    info "Tunnel established! The https://rc-*.radeon.firstdg.ai shown above is the public access URL"
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "  The public access URL has been generated; copy the URL shown above"
    echo "  View status: bash scripts/setup_tunnel.sh status"
    echo "  View logs:   bash scripts/setup_tunnel.sh logs"
    echo "  Stop tunnel: bash scripts/setup_tunnel.sh stop"
    echo "══════════════════════════════════════════════════════"
}

# ── view status ──
do_status() {
    step "Tunnel status:"
    "$RC_TUNNEL" status
    echo ""
    step "Local service status:"
    if curl --fail --silent --max-time 3 "http://127.0.0.1:${EXPOSE_PORT}/api/health" 2>/dev/null; then
        echo ""
        info "Agent service is healthy"
    else
        warn "Agent service is not responding or /api/health is unavailable"
    fi
}

# ── view logs ──
do_logs() {
    step "Tunnel logs (last 100 lines):"
    "$RC_TUNNEL" logs --lines 100
}

# ── stop the tunnel ──
do_stop() {
    step "Stopping the tunnel..."
    "$RC_TUNNEL" stop
    info "Tunnel stopped; the public URL is now invalid"
    warn "The domain prefix enters a 24-hour freeze period"
}

# ── main logic ──
case "${1:-help}" in
    install)
        do_install
        ;;
    expose)
        do_expose
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    stop)
        do_stop
        ;;
    *)
        echo "Usage: bash scripts/setup_tunnel.sh <command>"
        echo ""
        echo "Commands:"
        echo "  install   Install the rc-tunnel tool"
        echo "  expose    Expose port ${EXPOSE_PORT} to the public internet (generates a public URL)"
        echo "  status    View the tunnel and local service status"
        echo "  logs      View the tunnel logs"
        echo "  stop      Stop the tunnel (URL becomes invalid immediately)"
        echo ""
        echo "Typical flow:"
        echo "  1. bash scripts/setup_tunnel.sh install"
        echo "  2. python scripts/start_server.py   # in another terminal"
        echo "  3. bash scripts/setup_tunnel.sh expose"
        echo ""
        echo "Port notes:"
        echo "  8080 = Agent frontend (exposed to the public)"
        echo "  8000 = vLLM inference service (internal call, not exposed)"
        ;;
esac