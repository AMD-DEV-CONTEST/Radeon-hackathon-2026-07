#!/bin/bash
# init-cluster.sh — 首次启动后运行一次, 格式化 HDFS / 初始化 RM state / 启动 master daemons
# 用法: bash deploy/scripts/init-cluster.sh
# 前提: docker compose up -d (ZK + JN + DN + NM 已在 supervisord 中启动或 crash-loop 等待 format)
set -euo pipefail

echo "[init] 开始集群初始化..."

# ---- 1. 等 ZK quorum 建立 ----
echo "[init] 1/6 等待 ZooKeeper quorum..."
for n in hadoop01 hadoop02 hadoop03; do
  docker exec $n bash -c 'until echo srvr | nc localhost 2181 | grep -q Zookeeper; do sleep 2; done' || echo "  (等待 $n ZK...)"
done
sleep 3
echo "[init]     ZK quorum OK"

# ---- 2. 等 JournalNode 就绪 ----
echo "[init] 2/6 等待 JournalNode 就绪..."
for n in hadoop01 hadoop02 hadoop03; do
  docker exec $n bash -c 'until nc -z localhost 8485; do sleep 2; done' || echo "  (等待 $n JN...)"
done
echo "[init]     JN 就绪"

# ---- 3. 格式化 NN1 + 初始化 JN ----
echo "[init] 3/6 格式化 NN1..."
docker exec hadoop01 bash -c '
  if [ ! -d /data/hadoop/hdfs/name/current ]; then
    supervisorctl stop namenode zkfc 2>/dev/null || true
    hdfs namenode -format -force -nonInteractive
    hdfs namenode -initializeSharedEdits -nonInteractive
    supervisorctl start namenode zkfc
    echo "  NN1 格式化完成, JN 共享 edit 已初始化"
  else
    echo "  NN1 已有数据, 跳过 format"
  fi
'

# ---- 4. 等 NN1 active -> bootstrap NN2 ----
echo "[init] 4/6 等 NN1 成为 active..."
docker exec hadoop01 bash -c '
  for i in $(seq 1 30); do
    state=$(hdfs haadmin -getServiceState nn1 2>/dev/null || true)
    if [ "$state" = "active" ]; then
      echo "  NN1 active"
      exit 0
    fi
    sleep 2
  done
  echo "  WARN: NN1 未在 60s 内变 active, 继续尝试"
'

echo "[init]     bootstrap NN2..."
docker exec hadoop02 bash -c '
  if [ ! -d /data/hadoop/hdfs/name/current ]; then
    supervisorctl stop namenode zkfc 2>/dev/null || true
    hdfs namenode -bootstrapStandby -nonInteractive
    supervisorctl start namenode zkfc
    echo "  NN2 bootstrap 完成"
  else
    echo "  NN2 已有数据, 跳过 bootstrap"
  fi
'

# ---- 5. 格式 RM state-store + 启动 RM ----
echo "[init] 5/6 格式化 RM ZK state-store..."
docker exec hadoop01 bash -c '
  yarn resourcemanager -format-state-store -force 2>&1 || true
  supervisorctl start resourcemanager 2>/dev/null || true
  echo "  RM1 格式化完成, 已启动"
'
docker exec hadoop02 bash -c '
  supervisorctl start resourcemanager 2>/dev/null || true
  echo "  RM2 已启动"
'

# ---- 6. 等 DN + NM 注册 ----
echo "[init] 6/6 等待 DN / NM 注册 (最多 45s)..."
sleep 15
docker exec hadoop01 bash -c 'echo "  === HDFS dfsadmin ===" && hdfs dfsadmin -report 2>&1 | head -25' || echo "  (dfsadmin 尚未就绪, 继续...)"

echo ""
echo "============================================"
echo "  集群初始化完成"
echo "  NN active : http://localhost:9870 (hadoop01)"
echo "  NN standby: http://localhost:9871 (hadoop02)"
echo "  RM active : http://localhost:8088 (hadoop01)"
echo "  RM standby: http://localhost:8081 (hadoop02)"
echo "  JHS       : http://localhost:19888"
echo "  Grafana   : http://localhost:3000 (admin/admin)"
echo "  Prometheus: http://localhost:9090"
echo "============================================"
