#!/bin/bash
set -e

echo "=== Dify OpenAI Adapter Setup ==="

# 1. Create docker-compose.override.yaml
echo "[1/4] Creating docker-compose.override.yaml..."
cat > /tmp/docker-compose.override.yaml << 'OVERRIDE'
services:
  openai-adapter:
    image: dify-openai-adapter:latest
    container_name: openai-adapter
    restart: always
    environment:
      DIFY_API_URL: http://api:5001
      PORT: "8080"
    networks:
      - default
    expose:
      - "8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
OVERRIDE

sudo cp /tmp/docker-compose.override.yaml /root/dify/docker/docker-compose.override.yaml

# 2. Update nginx config
echo "[2/4] Updating nginx config..."
sudo cp /root/dify/docker/nginx/conf.d/default.conf /root/dify/docker/nginx/conf.d/default.conf.bak.$(date +%Y%m%d%H%M%S)

sudo sed -i '/location \/v1 {/i\
    # OpenAI-compatible API adapter\
    location /v1/chat/completions {\
      proxy_pass http://openai-adapter:8080;\
      include proxy.conf;\
      proxy_read_timeout 120s;\
    }\
\
    location /v1/models {\
      proxy_pass http://openai-adapter:8080;\
      include proxy.conf;\
    }\
' /root/dify/docker/nginx/conf.d/default.conf

echo "Nginx config snippet:"
grep -A2 'openai-adapter' /root/dify/docker/nginx/conf.d/default.conf

# 3. Start the adapter service
echo "[3/4] Starting openai-adapter service..."
cd /root/dify/docker
sudo docker compose up -d openai-adapter

# 4. Reload nginx
echo "[4/4] Reloading nginx..."
sudo docker compose restart nginx

echo ""
echo "=== Setup complete ==="
echo "Adapter logs: sudo docker logs openai-adapter"
