#!/usr/bin/env bash
# run_ornith_397b.sh — Download Ornith-1.0-397B-Q3_K_M and benchmark via llama.cpp on MI300X
set -e
DROPLET="root@134.199.203.198"
MODEL_DIR="/shared-docker/models/Ornith-1.0-397B-Q3KM"
GGUF_FILE="deepreinforce-ai_Ornith-1.0-397B-Q3_K_M.gguf"
REPO="bartowski/deepreinforce-ai_Ornith-1.0-397B-GGUF"
PORT=8080
DISPLAY_NAME="Ornith-1.0-397B-Q3K_M"
QUAL_LAB_DIR="/home/cesarops/cesarops_push/core/forge-qualification-lab"
DROPLET_IP="134.199.203.198"

echo "=== Ornith-1.0-397B-Q3_K_M on MI300X ==="
echo "Disk check..."
ssh $DROPLET "df -h /"

echo ""
echo "Downloading Q3_K_M (181GB) from bartowski..."
ssh $DROPLET "docker exec rocm bash -c 'hf download $REPO --local-dir $MODEL_DIR --include \"*Q3_K_M*\"'"

echo ""
echo "Checking llama-server in ROCm container..."
# Try running llama-server from the container; if missing, install via pip
ssh $DROPLET "docker exec rocm bash -c 'which llama-server 2>/dev/null || python3 -m llama_cpp.server --help 2>/dev/null | head -2 || echo MISSING'"

echo ""
echo "Killing old socat, restarting port forward..."
ssh $DROPLET "kill \$(pgrep socat) 2>/dev/null; sleep 1; nohup socat TCP-LISTEN:$PORT,fork TCP:172.17.0.2:$PORT >/dev/null 2>&1 &"

echo ""
echo "Deploying via Forge sidecar (llama.cpp engine)..."
curl -s -X POST http://localhost:9100/orchestrator/deploy \
  -H "Content-Type: application/json" \
  -d "{\"model_name\":\"Ornith-1.0-397B-Q3KM\",\"target_node\":\"mi300\",\"engine\":\"llama.cpp\",\"backend\":\"cuda\"}"
echo ""

echo "Waiting for server (up to 5 min for 181GB model)..."
for i in $(seq 1 60); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$DROPLET_IP:$PORT/v1/models 2>/dev/null || echo 0)
  if [ "$STATUS" = "200" ]; then
    echo "Server UP!"
    break
  fi
  echo -n "."
  sleep 5
done

SERVING_ID=$(curl -s http://$DROPLET_IP:$PORT/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['id'])" 2>/dev/null || echo "Ornith-1.0-397B-Q3KM")
echo "Serving ID: $SERVING_ID"

echo ""
echo "Running qualification..."
cargo run --example run_qualification -- \
  "http://$DROPLET_IP:$PORT" \
  "$SERVING_ID" \
  "llama.cpp" \
  "Q3_K_M" \
  "mi300" \
  "$DISPLAY_NAME"

echo ""
echo "Tearing down..."
curl -s -X POST http://localhost:9100/orchestrator/teardown \
  -H "Content-Type: application/json" \
  -d '{"target_node":"mi300"}'

echo ""
echo "Deleting model from disk..."
ssh $DROPLET "rm -rf $MODEL_DIR"

echo ""
echo "Done! Check scorecard at: $QUAL_LAB_DIR/reports/qualification/thomas-translator/$DISPLAY_NAME/"
