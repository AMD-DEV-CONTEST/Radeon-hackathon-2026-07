#!/usr/bin/env bash
# Deploy investor deck to MetaHub server 43.156.102.67 — Nginx /deck/ only, does NOT touch :3000.
#
#   ./scripts/deploy-investor-deck.sh
#   DECK_HOST=ubuntu@43.156.102.67 ./scripts/deploy-investor-deck.sh
#
# Requires SSH key to ubuntu@host. Passwords go in password manager only.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/docs/presentations"
HOST="${DECK_HOST:-root@43.156.102.67}"
REMOTE_DIR="${DECK_REMOTE_DIR:-/var/www/botversex-deck}"
NGINX_SITE="${DECK_NGINX_SITE:-botversex-deck}"

echo "==> Target: $HOST (MetaHub machine — deck on /deck/, New-API stays on :3000)"
echo "==> Sync static files to $REMOTE_DIR"
ssh "$HOST" "mkdir -p '$REMOTE_DIR'"
rsync -avz \
  "$SRC/deck-index.html" \
  "$SRC/investor-deck.html" \
  "$SRC/investor-teaser-deck.html" \
  "$SRC/investor-full-deck.html" \
  "$SRC/investor-seed-teaser-2026.html" \
  "$SRC/investor-seed-2026.html" \
  "$SRC/story-deck.html" \
  "$SRC/story-vision-2026.html" \
  "$HOST:$REMOTE_DIR/"
rsync -avz --delete "$SRC/assets/" "$HOST:$REMOTE_DIR/assets/"

echo "==> Install Nginx site (path /deck/ only)"
scp "$SRC/deploy/nginx-metahub-deck.conf" "$HOST:/tmp/nginx-${NGINX_SITE}.conf"
ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
cp /tmp/nginx-${NGINX_SITE}.conf /etc/nginx/sites-available/${NGINX_SITE}
ln -sf /etc/nginx/sites-available/${NGINX_SITE} /etc/nginx/sites-enabled/${NGINX_SITE}
nginx -t
systemctl reload nginx
REMOTE

IP="$(echo "$HOST" | cut -d@ -f2)"
echo ""
echo "Done. Deck links:"
echo "  http://${IP}/deck/                    (index)"
echo "  http://${IP}/deck/story-deck.html      (愿景故事 · 无融资)"
echo "  http://${IP}/deck/investor-deck.html       (投资人 Teaser 15 页)"
echo "  http://${IP}/deck/investor-full-deck.html  (投资人 Deep Dive 45 页)"
echo "MetaHub unchanged: http://${IP}:3000"
