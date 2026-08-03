#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${YIJIAN_BASE_URL:-http://127.0.0.1:8600}"
echo "=== AMD hardware ==="
amd-smi static --asic --vram --driver --bus || true
echo "=== GoMentor health ==="
curl -fsS "$BASE_URL/api/health" | python3 -m json.tool
echo "=== Mentor providers ==="
curl -fsS "$BASE_URL/api/mentor/status?force=true" | python3 -m json.tool
echo "=== Cloud model ==="
curl -fsS http://127.0.0.1:8082/v1/models | python3 -m json.tool
echo "=== 4B baseline model ==="
curl -fsS http://127.0.0.1:8081/v1/models | python3 -m json.tool
