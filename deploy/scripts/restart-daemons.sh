#!/bin/bash
# restart-daemons.sh — 非首次启动时重启 master daemons (NN/ZKFC/RM/HMS/HS2/HMaster)
# 用法: bash deploy/scripts/restart-daemons.sh
# 前提: docker compose up -d (容器已启动, 数据卷已存在)
set -euo pipefail

echo "[restart] 重启 master daemons..."

# hadoop01: NN1 + ZKFC + RM1 + JHS + HMS + HS2 + HMaster
echo "[restart] hadoop01 master daemons..."
docker exec hadoop01 supervisorctl start namenode zkfc resourcemanager historyserver hivemetastore hiveserver2 hmaster 2>/dev/null || true

# hadoop02: NN2 + ZKFC + RM2 + HMS + HS2 + HMaster(backup)
echo "[restart] hadoop02 master daemons..."
docker exec hadoop02 supervisorctl start namenode zkfc resourcemanager hivemetastore hiveserver2 hmaster 2>/dev/null || true

echo "[restart] 等待服务就绪 (15s)..."
sleep 15

echo "[restart] 检查状态..."
docker exec hadoop01 bash -c '
  echo "=== HDFS HA ==="
  hdfs haadmin -getAllServiceState 2>&1
  echo ""
  echo "=== YARN RM HA ==="
  yarn rmadmin -getAllServiceState 2>&1
  echo ""
  echo "=== HDFS DataNodes ==="
  hdfs dfsadmin -report 2>&1 | head -15
'

echo ""
echo "============================================"
echo "  集群已恢复运行"
echo "  NN active : http://localhost:9870 (hadoop01)"
echo "  NN standby: http://localhost:9871 (hadoop02)"
echo "  RM active : http://localhost:8088 (hadoop01)"
echo "  RM standby: http://localhost:8081 (hadoop02)"
echo "  JHS       : http://localhost:19888"
echo "  HBase     : http://localhost:16010"
echo "  Grafana   : http://localhost:3000 (admin/admin)"
echo "  Prometheus: http://localhost:9090"
echo "============================================"
