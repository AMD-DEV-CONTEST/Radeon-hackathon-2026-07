#!/bin/bash
# reset.sh — 彻底摧毁: 停容器 + 删数据卷 + 删镜像 (回到出厂状态)
set -euo pipefail
cd "$(dirname "$0")"
docker compose down -v
docker rmi aiops-hadoop:step1 2>/dev/null || true
echo "已彻底清除-容器+数据卷+镜像。"
echo "从头再来: bash deploy/up.sh && bash deploy/scripts/init-cluster.sh"
