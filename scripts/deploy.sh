#!/usr/bin/env bash
# BotverseX production deploy script (ECS-safe)
#
# Designed to coexist with existing sites on the same server.
# BotverseX binds only to 127.0.0.1:18080; the system nginx
# reverse-proxies botversex.achao.xin (and legacy botversex.feispace.me) to it.
#
# Usage (on the ECS server):
#   1. Upload the repo to /opt/botversex
#   2. Run:  bash scripts/deploy.sh
#
# Prerequisites:
#   - 2+ cores, 8GB+ RAM recommended
#   - DNS A record: botversex.achao.xin -> <server public IP>
#   - Optional legacy: botversex.feispace.me -> same IP
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/infra/docker/docker-compose.prod.yml"
DOMAIN="botversex.achao.xin"
DOMAIN_ALT="botversex.feispace.me"
SERVER_NAMES="$DOMAIN $DOMAIN_ALT"
VHOST_CONF="/etc/nginx/conf.d/botversex.conf"
INTERNAL_PORT="18080"

echo "============================================"
echo " BotverseX Production Deploy"
echo " Root:   $ROOT"
echo " Domain: $DOMAIN (alt: $DOMAIN_ALT)"
echo "============================================"

# --- 1. Install Docker if not present ---
if ! command -v docker &>/dev/null; then
  echo "[deploy] Docker not found. Installing..."
  if command -v dnf &>/dev/null; then
    dnf install -y docker
  elif command -v yum &>/dev/null; then
    yum install -y docker
  elif command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq docker.io
  else
    curl -fsSL https://get.docker.com | bash
  fi
  systemctl enable --now docker 2>/dev/null || true
  echo "[deploy] Docker installed."
fi

if docker compose version &>/dev/null; then
  COMPOSE=(docker compose)
elif command -v podman-compose &>/dev/null; then
  COMPOSE=(podman-compose)
else
  echo "[deploy] compose command not found. Installing..."
  if command -v dnf &>/dev/null; then
    dnf install -y podman-compose docker-compose-plugin 2>/dev/null || dnf install -y podman-compose
  elif command -v yum &>/dev/null; then
    yum install -y podman-compose docker-compose-plugin 2>/dev/null || yum install -y podman-compose
  elif command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
  fi

  if docker compose version &>/dev/null; then
    COMPOSE=(docker compose)
  elif command -v podman-compose &>/dev/null; then
    COMPOSE=(podman-compose)
  else
    echo "[deploy] ERROR: neither docker compose nor podman-compose is available."
    exit 1
  fi
fi

echo "[deploy] Docker $(docker --version)"
echo "[deploy] Compose command: ${COMPOSE[*]}"

# --- 2. Build and start containers ---
echo "[deploy] Building and starting services..."
cd "$ROOT"
"${COMPOSE[@]}" -f "$COMPOSE_FILE" up -d --build

echo "[deploy] Waiting for API container to be ready..."
for i in $(seq 1 30); do
  sleep 2
  if "${COMPOSE[@]}" -f "$COMPOSE_FILE" exec -T api python -c "print('ok')" 2>/dev/null; then
    echo "[deploy] API container ready after ${i}x2s"
    break
  fi
done

# --- 3. Run database migration ---
echo "[deploy] Running M17 migration..."
"${COMPOSE[@]}" -f "$COMPOSE_FILE" exec -T api \
  python -m app.migrations.m17_subscription 2>&1 || true

# --- 4. Create nginx vhost (if not already present) ---
if [ -f "$VHOST_CONF" ]; then
  echo "[deploy] nginx vhost already exists at $VHOST_CONF, skipping creation."
else
  echo "[deploy] Creating nginx vhost for $DOMAIN ..."

  # Backup existing nginx config first
  if [ -d /etc/nginx ]; then
    BACKUP="/etc/nginx.backup.$(date +%F-%H%M%S)"
    cp -a /etc/nginx "$BACKUP"
    echo "[deploy] nginx config backed up to $BACKUP"
  fi

  # Dedicated cert (SAN both domains). Issue once on the server:
  # acme.sh --issue -d botversex.achao.xin -d botversex.feispace.me -w /var/www/acme-challenge
  SSL_CERT="/etc/nginx/ssl/botversex/fullchain.cer"
  SSL_KEY="/etc/nginx/ssl/botversex/privkey.key"
  mkdir -p /etc/nginx/ssl/botversex /var/www/acme-challenge/.well-known/acme-challenge

  cat > "$VHOST_CONF" <<NGINX
server {
    listen 80;
    server_name ${SERVER_NAMES};

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme-challenge;
        default_type "text/plain";
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name ${SERVER_NAMES};

    ssl_certificate ${SSL_CERT};
    ssl_certificate_key ${SSL_KEY};
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:${INTERNAL_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
NGINX

  echo "[deploy] Wrote $VHOST_CONF"

  # Test and reload nginx only if test passes
  if nginx -t 2>&1; then
    nginx -s reload
    echo "[deploy] nginx reloaded successfully."
  else
    echo "[deploy] WARNING: nginx -t failed! Removing new vhost to protect existing sites."
    rm -f "$VHOST_CONF"
    echo "[deploy] Removed $VHOST_CONF. Please check nginx config manually."
  fi
fi

# --- 5. Health check ---
echo ""
echo "[deploy] Health check..."
sleep 3

WEB_OK=false
API_OK=false
RT_OK=false

curl -sS --noproxy '*' -o /dev/null -w '%{http_code}' "http://127.0.0.1:${INTERNAL_PORT}" 2>/dev/null | grep -q '^2' && WEB_OK=true
"${COMPOSE[@]}" -f "$COMPOSE_FILE" exec -T api curl -sS http://127.0.0.1:8000/health 2>/dev/null && API_OK=true || true
"${COMPOSE[@]}" -f "$COMPOSE_FILE" exec -T realtime curl -sS http://127.0.0.1:8002/api/setup/health 2>/dev/null && RT_OK=true || true

echo ""
echo "============================================"
echo " Deploy result"
echo "============================================"
echo " Web  (127.0.0.1:${INTERNAL_PORT}): $WEB_OK"
echo " API  (internal :8000):              $API_OK"
echo " Realtime (internal :8002):          $RT_OK"
echo ""
echo " Public URL: https://$DOMAIN"
echo "============================================"

if [ "$WEB_OK" = true ]; then
  echo ""
  echo "[deploy] Done! Open https://$DOMAIN in a browser."
  echo ""
  echo " Existing sites are NOT affected:"
  echo "   http://feispace.me      -> blog (unchanged)"
  echo "   https://$DOMAIN -> BotverseX (primary)"
  echo "   https://$DOMAIN_ALT -> BotverseX (legacy)"
else
  echo ""
  echo "[deploy] Some services may still be starting. Check logs:"
  echo "  ${COMPOSE[*]} -f $COMPOSE_FILE logs -f"
fi

echo ""
echo " Useful commands:"
echo "   ${COMPOSE[*]} -f $COMPOSE_FILE logs -f        # live logs"
echo "   ${COMPOSE[*]} -f $COMPOSE_FILE ps              # container status"
echo "   ${COMPOSE[*]} -f $COMPOSE_FILE down            # stop all"
echo "   ${COMPOSE[*]} -f $COMPOSE_FILE up -d --build   # rebuild & restart"
