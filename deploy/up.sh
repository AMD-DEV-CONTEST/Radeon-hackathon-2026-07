#!/bin/bash
# up.sh — 构建镜像 + 启动集群
set -euo pipefail
cd "$(dirname "$0")"
echo "=== Step 1: docker compose build (首次构建 aiops-hadoop:step1, ~5-10 min) ==="
docker compose build
echo "=== Step 2: docker compose up -d ==="
docker compose up -d
echo ""
echo "容器已启动 (ZK + JN + DN + NM 已在运行, NN/RM 等待 init)。"
echo "首次运行请执行: bash deploy/scripts/init-cluster.sh"
echo "非首次运行请执行: bash deploy/scripts/restart-daemons.sh"
echo "查看状态: docker compose ps"
