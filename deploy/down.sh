#!/bin/bash
# down.sh — 停止集群 (保留数据卷)
set -euo pipefail
cd "$(dirname "$0")"
docker compose down
echo "集群已停止, 数据卷保留。重新启动: bash deploy/up.sh"
