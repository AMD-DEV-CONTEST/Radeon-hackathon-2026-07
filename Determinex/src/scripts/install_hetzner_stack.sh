#!/bin/bash
# install_hetzner_stack.sh — bootstraps the full Determinex ops stack on Hetzner.
# Run on Hetzner as root.
#
# Installs / configures:
#   1. Tailscale (zero-config wireguard mesh — no more SSH key juggling)
#   2. Docker daemon (already present, but verify)
#   3. k3s lightweight Kubernetes (replaces raw docker for orchestration)
#   4. OpenTelemetry Collector (traces → Grafana Tempo)
#   5. Monitoring docker-compose stack (uptime-kuma/grafana/loki/postgres/redis/n8n/memos/vault)
#   6. Webhook notifier env wiring
#
# Idempotent — safe to re-run.
set -uo pipefail

DETERMINEX_NOTIFY_URL="${DETERMINEX_NOTIFY_URL:-}"
TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-determinex_$(openssl rand -hex 16)}"
COMPOSE_DIR="/root/determinex-ops"

echo "=== Determinex Hetzner Stack Installer ==="
echo

# 1. Tailscale
if ! command -v tailscale >/dev/null; then
    echo "[1/6] Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    if [ -n "$TAILSCALE_AUTHKEY" ]; then
        tailscale up --authkey "$TAILSCALE_AUTHKEY" --hostname determinex-eval
    else
        echo "  set TAILSCALE_AUTHKEY env to auto-join the tailnet"
        echo "  or run: tailscale up   (will print a login URL)"
    fi
else
    echo "[1/6] Tailscale already installed"
fi

# 2. Docker check
if ! command -v docker >/dev/null; then
    echo "[2/6] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
else
    echo "[2/6] Docker $(docker --version) present"
fi

# 3. k3s
if ! command -v k3s >/dev/null; then
    echo "[3/6] Installing k3s..."
    curl -sfL https://get.k3s.io | sh -
    mkdir -p /root/.kube && cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
    echo "  k3s installed; kubectl available as 'k3s kubectl'"
else
    echo "[3/6] k3s already installed"
fi

# 4. OpenTelemetry Collector
if ! docker ps --format '{{.Names}}' | grep -q determinex-otel; then
    echo "[4/6] Starting OpenTelemetry Collector..."
    cat > /etc/determinex-otel-config.yaml <<'EOF'
receivers:
  otlp:
    protocols:
      grpc: {endpoint: 0.0.0.0:4317}
      http: {endpoint: 0.0.0.0:4318}
processors:
  batch: {}
exporters:
  loki: {endpoint: http://localhost:3100/loki/api/v1/push}
  prometheus: {endpoint: 0.0.0.0:8889}
  logging: {loglevel: info}
service:
  pipelines:
    traces: {receivers: [otlp], processors: [batch], exporters: [logging]}
    metrics: {receivers: [otlp], processors: [batch], exporters: [prometheus]}
    logs: {receivers: [otlp], processors: [batch], exporters: [loki]}
EOF
    docker run -d --name determinex-otel --restart unless-stopped \
        -p 4317:4317 -p 4318:4318 -p 8889:8889 \
        --network host \
        -v /etc/determinex-otel-config.yaml:/etc/otelcol/config.yaml:ro \
        otel/opentelemetry-collector-contrib:latest --config /etc/otelcol/config.yaml
else
    echo "[4/6] OpenTelemetry Collector already running"
fi

# 5. Monitoring stack
echo "[5/6] Deploying monitoring stack..."
mkdir -p "$COMPOSE_DIR"
# (assumes user has scp'd the docker-compose.yml + configs to $COMPOSE_DIR)
if [ ! -f "$COMPOSE_DIR/docker-compose.yml" ]; then
    echo "  WARNING: $COMPOSE_DIR/docker-compose.yml not found"
    echo "  Run from local: scp -r docker/monitoring/* root@5.78.192.163:$COMPOSE_DIR/"
else
    cd "$COMPOSE_DIR"
    cat > .env <<EOF
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
VAULT_ROOT_TOKEN=$(openssl rand -hex 16)
N8N_HOST=$(hostname)
EOF
    docker compose up -d
fi

# 6. Webhook env
if [ -n "$DETERMINEX_NOTIFY_URL" ]; then
    echo "[6/6] Wiring webhook env..."
    echo "export DETERMINEX_NOTIFY_URL='$DETERMINEX_NOTIFY_URL'" > /etc/profile.d/determinex.sh
    echo "  set DETERMINEX_NOTIFY_URL in /etc/profile.d/determinex.sh"
else
    echo "[6/6] DETERMINEX_NOTIFY_URL not set; skipping webhook wiring"
fi

echo
echo "=== Done ==="
echo "Access (over Tailscale if configured, else public IP):"
echo "  - Grafana:     http://$(hostname):3000  (anonymous-admin enabled)"
echo "  - uptime-kuma: http://$(hostname):3001"
echo "  - n8n:         http://$(hostname):5678"
echo "  - memos:       http://$(hostname):5230"
echo "  - vault:       http://$(hostname):8200  (root token in $COMPOSE_DIR/.env)"
echo "  - Prometheus:  http://$(hostname):9090"
echo "  - Loki:        http://$(hostname):3100"
echo
echo "Worker.sh upgrade: cp scripts/worker_v2.sh /root/queue/worker.sh"
