#!/bin/bash
# B6: 本地模型回归评测（Qwen3-8B on AMD Radeon，与云端 35B 分开报告）
# 用法：bash scripts/run-local-regression.sh <pilot_goldset> <output_suffix>
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PILOT="${1:-evals/configs/gold-set-severe-draft-v1.json}"
SUFFIX="${2:-local-8b}"
PORT="${3:-3001}"

export ADMIN_API_KEY=$(grep '^ADMIN_API_KEY=' .env.local | cut -d= -f2- | tr -d '"')

echo "=== B6: 本地模型回归（Qwen3-8B）==="
echo "Gold Set: $PILOT"
echo "注意：本地模型结果与云端 35B 分开报告，不合并。"

# 1. 确保隧道存活（本地:8000 → AMD 实例 vLLM）
if ! curl -s -m 5 http://127.0.0.1:8000/v1/models >/dev/null 2>&1; then
  echo "隧道不可用，尝试重建..."
  ssh -f -N -L 8000:localhost:8000 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -p 31313 root@36.150.116.206 || { echo "隧道重建失败"; exit 1; }
  sleep 3
fi

# 2. 重启 QA 服务（指向本地 vLLM）
pkill -f "next dev -p $PORT" 2>/dev/null || true
sleep 2
AMD_API_URL="http://127.0.0.1:8000/v1/chat/completions" \
AMD_API_KEY=local \
AMD_MODEL="/workspace/Qwen3-8B" \
QA_LLM_PROVIDER=amd \
NODE_OPTIONS=--max-old-space-size=4096 \
nohup npx next dev -p "$PORT" > "/tmp/qa-server-local-$SUFFIX.log" 2>&1 &
sleep 12
curl -s -m 5 "http://localhost:$PORT/api/health" >/dev/null || { echo "QA 服务未就绪"; tail -10 /tmp/qa-server-local-$SUFFIX.log; exit 1; }
echo "QA 服务就绪（端口 $PORT，本地模型）"

# 3. 跑 pilot 配对消融（本地模型）
node scripts/evaluate-goldset.mjs \
  --goldsets "$PILOT" \
  --variants rule_only,dual,agent \
  --paired \
  --base-url "http://localhost:$PORT" \
  --concurrency 2 \
  --api-key "$ADMIN_API_KEY"

echo "=== B6 完成（本地 Qwen3-8B 结果，见 evals/results/）==="
