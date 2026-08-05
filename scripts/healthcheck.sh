#!/bin/bash
# ============================================================
# Hadoop Cluster Health Check Script (Docker 3-node HA / single-node direct install)
# Usage: bash scripts/healthcheck.sh
# ============================================================

# Note: set -e is intentionally omitted so a single failed check
# does not abort the entire script.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

FAILED=0

check_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
check_fail() { echo -e "${RED}[FAIL]${NC} $1"; FAILED=1; }
check_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# ============================================================
# Detect cluster mode: Docker (docker exec) or direct install (supervisorctl)
# ============================================================
SUPCTL="supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf"

if docker exec hadoop01 echo OK >/dev/null 2>&1; then
  MODE="docker"
  NODES=(hadoop01 hadoop02 hadoop03)
  EXPECTED_DN=3
elif bash -c "$SUPCTL status" >/dev/null 2>&1; then
  MODE="direct"
  NODES=(localhost)
  EXPECTED_DN=1
else
  echo -e "${RED}[ERROR]${NC} Hadoop cluster not running (neither Docker nor direct install detected)"
  exit 1
fi

echo "============================================================"
echo "  Hadoop Cluster Health Check"
echo "  Mode: $MODE"
echo "  Time: $(date)"
echo "============================================================"
echo ""

# ============================================================
# Cluster operation wrappers (consistent with inject-fault.sh)
# ============================================================
cluster_exec() {
  local node="$1"; shift
  if [ "$MODE" = "docker" ]; then
    docker exec "$node" "$@"
  else
    "$@"
  fi
}

get_jps() {
  local node="$1"
  if [ "$MODE" = "docker" ]; then
    docker exec "$node" jps 2>/dev/null
  else
    /usr/bin/jps 2>/dev/null
  fi
}

get_hdfs_report() {
  if [ "$MODE" = "docker" ]; then
    docker exec hadoop01 bash -c 'export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64; /opt/hadoop/bin/hdfs dfsadmin -report 2>/dev/null'
  else
    /opt/hadoop/bin/hdfs dfsadmin -report 2>/dev/null
  fi
}

# ============================================================
# Per-node checks
# ============================================================
for node in "${NODES[@]}"; do
  echo ">>> Node: $node"
  echo ""

  # Container/process check
  if [ "$MODE" = "docker" ]; then
    if ! docker exec "$node" echo OK 2>/dev/null | grep -q OK; then
      check_fail "Container not running"
      echo ""
      continue
    fi
    check_pass "Container running"
  else
    check_pass "Direct install (localhost)"
  fi

  # Java process checks (Docker: by node role, direct: check all)
  JPS=$(get_jps "$node")
  case "$node" in
    hadoop01)
      for proc in NameNode DataNode JournalNode ResourceManager NodeManager JobHistoryServer HMaster HRegionServer QuorumPeerMain DFSZKFailoverController; do
        if echo "$JPS" | grep -q "$proc"; then check_pass "Process: $proc"; else check_fail "Process: $proc"; fi
      done
      # Docker hadoop01 may also have Hive
      for proc in RunJar; do
        COUNT=$(echo "$JPS" | grep -c "$proc" || true)
        if [ "$COUNT" -ge 2 ]; then check_pass "Process: Hive (MetaStore+Server2)"; else check_warn "Process: Hive (expected 2 RunJar, got $COUNT)"; fi
      done
      ;;
    hadoop02)
      for proc in NameNode DataNode JournalNode ResourceManager NodeManager HMaster HRegionServer QuorumPeerMain DFSZKFailoverController; do
        if echo "$JPS" | grep -q "$proc"; then check_pass "Process: $proc"; else check_fail "Process: $proc"; fi
      done
      for proc in RunJar; do
        COUNT=$(echo "$JPS" | grep -c "$proc" || true)
        if [ "$COUNT" -ge 2 ]; then check_pass "Process: Hive (MetaStore+Server2)"; else check_warn "Process: Hive (expected 2 RunJar, got $COUNT)"; fi
      done
      ;;
    hadoop03)
      for proc in DataNode JournalNode NodeManager HRegionServer QuorumPeerMain; do
        if echo "$JPS" | grep -q "$proc"; then check_pass "Process: $proc"; else check_fail "Process: $proc"; fi
      done
      ;;
    localhost)
      # Direct install single-node: all processes on one node
      for proc in NameNode DataNode ResourceManager NodeManager JobHistoryServer HMaster HRegionServer QuorumPeerMain; do
        if echo "$JPS" | grep -q "$proc"; then check_pass "Process: $proc"; else check_fail "Process: $proc"; fi
      done
      # Hive (RunJar x2: MetaStore + Server2)
      RUNJAR_COUNT=$(echo "$JPS" | grep -c "RunJar" || true)
      if [ "$RUNJAR_COUNT" -ge 2 ]; then
        check_pass "Process: Hive (MetaStore+Server2)"
      else
        check_warn "Process: Hive (expected 2 RunJar, got $RUNJAR_COUNT)"
      fi
      ;;
  esac
  echo ""

  # HBase Master (hadoop01/02 or localhost)
  if [ "$node" = "hadoop01" ] || [ "$node" = "hadoop02" ] || [ "$node" = "localhost" ]; then
    echo "  [HBase]"
    HBASE=$(cluster_exec "$node" curl -s http://localhost:16010/jmx 2>/dev/null)
    if echo "$HBASE" | grep -q "tag.isActiveMaster"; then
      IS_ACTIVE=$(echo "$HBASE" | grep "tag.isActiveMaster" | head -1 | grep -o "true\|false")
      if [ "$IS_ACTIVE" = "true" ]; then check_pass "Master: ACTIVE"; else check_pass "Master: STANDBY"; fi
    else
      check_fail "Master status"
    fi
    echo ""
  fi

  # ZooKeeper
  echo "  [ZooKeeper]"
  if cluster_exec "$node" nc -z localhost 2181 2>/dev/null; then
    check_pass "Port 2181 reachable"
  else
    check_fail "Port 2181 unreachable"
  fi
  echo ""

  # Hive (hadoop01/02 or localhost)
  if [ "$node" = "hadoop01" ] || [ "$node" = "hadoop02" ] || [ "$node" = "localhost" ]; then
    echo "  [Hive]"
    if cluster_exec "$node" nc -z localhost 10000 2>/dev/null; then check_pass "HiveServer2 (10000)"; else check_fail "HiveServer2 (10000)"; fi
    if cluster_exec "$node" nc -z localhost 9083 2>/dev/null; then check_pass "MetaStore (9083)"; else check_fail "MetaStore (9083)"; fi
    echo ""
  fi

  echo "------------------------------------------------------------"
  echo ""
done

# ============================================================
# Cluster-level checks
# ============================================================
echo ">>> Cluster-level checks"
echo ""

# HDFS
echo "  [HDFS]"
REPORT=$(get_hdfs_report)
LIVE=$(echo "$REPORT" | grep -o "Live datanodes ([0-9]*)" | grep -o "[0-9]*")
LIVE=${LIVE:-0}
if [ "$LIVE" -eq "$EXPECTED_DN" ]; then check_pass "DataNode: $LIVE/$EXPECTED_DN"; else check_fail "DataNode: $LIVE/$EXPECTED_DN"; fi
MISSING=$(echo "$REPORT" | grep "Missing blocks:" | head -1 | awk '{print $3}')
MISSING=${MISSING:-0}
if [ "$MISSING" -eq 0 ]; then check_pass "Missing blocks: 0"; else check_warn "Missing blocks: $MISSING"; fi

# Read/write test
TEST="/tmp/hc_$(date +%s).txt"
if [ "$MODE" = "docker" ]; then
  if docker exec hadoop01 bash -c "echo test | hdfs dfs -put - $TEST && hdfs dfs -cat $TEST && hdfs dfs -rm $TEST" 2>/dev/null | grep -q test; then
    check_pass "Read/write test"
  else
    check_fail "Read/write test"
  fi
else
  if bash -c "echo test | /opt/hadoop/bin/hdfs dfs -put - $TEST && /opt/hadoop/bin/hdfs dfs -cat $TEST && /opt/hadoop/bin/hdfs dfs -rm $TEST" 2>/dev/null | grep -q test; then
    check_pass "Read/write test"
  else
    check_fail "Read/write test"
  fi
fi
echo ""

# YARN
echo "  [YARN]"
if [ "$MODE" = "docker" ]; then
  NODES_COUNT=$(docker exec hadoop01 yarn node -list 2>/dev/null | grep -c RUNNING)
else
  NODES_COUNT=$(/opt/hadoop/bin/yarn node -list 2>/dev/null | grep -c RUNNING)
fi
NODES_COUNT=${NODES_COUNT:-0}
if [ "$NODES_COUNT" -eq "$EXPECTED_DN" ]; then
  check_pass "NodeManager: $NODES_COUNT RUNNING"
else
  check_fail "NodeManager: $NODES_COUNT/$EXPECTED_DN"
fi

# HA state check (Docker mode only)
if [ "$MODE" = "docker" ]; then
  NN1=$(docker exec hadoop01 hdfs haadmin -getServiceState nn1 2>/dev/null || echo "unknown")
  NN2=$(docker exec hadoop01 hdfs haadmin -getServiceState nn2 2>/dev/null || echo "unknown")
  check_pass "NameNode HA: nn1=$NN1, nn2=$NN2"
  RM1=$(docker exec hadoop01 yarn rmadmin -getServiceState rm1 2>/dev/null || echo "unknown")
  RM2=$(docker exec hadoop01 yarn rmadmin -getServiceState rm2 2>/dev/null || echo "unknown")
  check_pass "ResourceManager HA: rm1=$RM1, rm2=$RM2"
else
  check_pass "Single-node (no HA)"
fi
echo ""

# JMX Exporter ports (direct install mode extra check)
if [ "$MODE" = "direct" ]; then
  echo "  [JMX Exporter]"
  for pair in "10101:NameNode" "10102:DataNode" "10104:ResourceManager" "10105:NodeManager" "10106:HistoryServer" "10107:HMaster" "10108:RegionServer" "10109:ZooKeeper" "10110:HiveMetaStore" "10111:HiveServer2"; do
    port="${pair%%:*}"
    name="${pair##*:}"
    if nc -z localhost "$port" 2>/dev/null; then
      check_pass "$name ($port)"
    else
      check_fail "$name ($port)"
    fi
  done
  echo ""
fi

# SSH ports (direct install mode extra check)
if [ "$MODE" = "direct" ]; then
  echo "  [SSH]"
  # Dynamically detect SSH listening ports.
  # Single-node direct install: only port 22 (setup-hadoop-direct.sh starts one sshd).
  # Legacy/Docker 3-node: ports 2222/2223/2224 (container port mapping).
  # Instead of hardcoding, discover actual sshd listeners to avoid false FAILs.
  SSH_PORTS=""
  if command -v ss >/dev/null 2>&1; then
    SSH_PORTS=$(ss -tlnp 2>/dev/null | grep sshd | awk '{print $4}' | awk -F: '{print $NF}' | sort -un)
  elif command -v netstat >/dev/null 2>&1; then
    SSH_PORTS=$(netstat -tlnp 2>/dev/null | grep sshd | awk '{print $4}' | awk -F: '{print $NF}' | sort -un)
  fi
  SSH_PORTS=${SSH_PORTS:-22}  # fallback to 22 if detection fails

  for p in $SSH_PORTS; do
    if nc -z localhost "$p" 2>/dev/null; then
      check_pass "Port $p"
    else
      check_fail "Port $p"
    fi
  done
  echo ""
fi

# Monitoring components (both modes)
echo "  [Monitoring]"
for pair in "9090:Prometheus" "3000:Grafana" "9093:Alertmanager"; do
  port="${pair%%:*}"
  name="${pair##*:}"
  if [ "$MODE" = "docker" ]; then
    # Docker mode: check container port mapping
    if nc -z localhost "$port" 2>/dev/null; then
      check_pass "$name ($port)"
    else
      check_warn "$name ($port) — may be on different port"
    fi
  else
    if nc -z localhost "$port" 2>/dev/null; then
      check_pass "$name ($port)"
    else
      check_fail "$name ($port)"
    fi
  fi
done
echo ""

# ============================================================
# Summary
# ============================================================
echo "============================================================"
if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}All checks passed!${NC}"
  exit 0
else
  echo -e "${RED}Some checks failed.${NC}"
  exit 1
fi
