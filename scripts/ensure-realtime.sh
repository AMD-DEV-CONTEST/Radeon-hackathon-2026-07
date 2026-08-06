#!/usr/bin/env bash
# Ensure BotverseX realtime is reachable on host :8002 (Docker web uses extra_hosts → host-gateway).
# Run on ECS as root; install: crontab -e → @reboot /opt/botversex/scripts/ensure-realtime.sh
set -euo pipefail
COMPOSE=/opt/botversex/infra/docker/docker-compose.prod.yml
HEALTH=http://127.0.0.1:8002/api/setup/health

healthy() {
  curl -sf --max-time 3 "$HEALTH" >/dev/null 2>&1
}

if healthy; then
  exit 0
fi

# Preferred: Docker realtime service (publish 8002 to host via compose port mapping if added)
if docker image inspect localhost/botversex/realtime:prod >/dev/null 2>&1; then
  docker rm -f botversex-realtime 2>/dev/null || true
  docker compose -f "$COMPOSE" up -d realtime
  for _ in $(seq 1 30); do
    sleep 2
    healthy && { echo "realtime ok (docker)"; exit 0; }
  done
fi

# Legacy fallback: libpod runc bundle + socat bridge (fragile after reboot)
BUNDLE=/var/lib/containers/storage/overlay-containers/5d6c09e85a37feb1abe4ca0d6ca82243d745d0f56416bac9b3ddd4d54760b89c/userdata
PIDFILE=/tmp/botversex-rt.pid

if [[ ! -f "$BUNDLE/config.json" ]]; then
  echo "realtime down; build image: docker compose -f $COMPOSE build realtime" >&2
  exit 1
fi

mkdir -p "$BUNDLE"
cp /etc/hosts "$BUNDLE/hosts" 2>/dev/null || echo "127.0.0.1 localhost" >"$BUNDLE/hosts"
cp /etc/resolv.conf "$BUNDLE/resolv.conf" 2>/dev/null || echo "nameserver 8.8.8.8" >"$BUNDLE/resolv.conf"

python3 - "$BUNDLE/config.json" <<'PY'
import json, sys
p = sys.argv[1]
with open(p) as f:
    c = json.load(f)
ns = [n for n in c["linux"]["namespaces"] if not (n.get("type") == "network" and "path" in n)]
if not any(n.get("type") == "network" for n in ns):
    ns.append({"type": "network"})
c["linux"]["namespaces"] = ns
with open(p, "w") as f:
    json.dump(c, f, indent=2)
PY

pkill -f "run_api.py --http" 2>/dev/null || true
sleep 1
/usr/bin/runc run -d --pid-file "$PIDFILE" --bundle "$BUNDLE" botversex-realtime || {
  echo "runc start failed; run: docker compose -f $COMPOSE build realtime && up -d realtime" >&2
  exit 1
}
sleep 4
PID=$(cat "$PIDFILE")
RT_IP=$(nsenter -t "$PID" -n ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
[[ -n "$RT_IP" ]] || { echo "no RT_IP" >&2; exit 1 }

pkill -f "socat TCP-LISTEN:8002" 2>/dev/null || true
sleep 1
nohup socat TCP-LISTEN:8002,bind=0.0.0.0,fork,reuseaddr "TCP:${RT_IP}:8002" >/tmp/botversex-socat.log 2>&1 &
sleep 2
healthy || { echo "realtime health check failed" >&2; exit 1; }
echo "realtime ok via runc+$RT_IP"
