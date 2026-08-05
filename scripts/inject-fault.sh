#!/usr/bin/env bash
# inject-fault.sh — Interactive fault injection + verification for AIOps Agent
#
# Usage:  bash scripts/inject-fault.sh
#
# Flow:  detect cluster → menu → inject → wait → [1) inject another  2) verify+report]
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ_DIR"

C_GREEN='\033[0;32m'; C_RED='\033[0;31m'; C_YELLOW='\033[1;33m'
C_CYAN='\033[0;36m';  C_BOLD='\033[1m';   C_MAGENTA='\033[0;35m'; NC='\033[0m'

log()    { echo -e "${C_CYAN}[$(date +%H:%M:%S)]${NC} $1"; }
ok()     { echo -e "${C_GREEN}[$(date +%H:%M:%S)] [OK]${NC} $1"; }
fail()   { echo -e "${C_RED}[$(date +%H:%M:%S)] [FAIL]${NC} $1"; }
warn()   { echo -e "${C_YELLOW}[$(date +%H:%M:%S)] [WARN]${NC} $1"; }
header() { echo -e "\n${C_BOLD}${C_MAGENTA}════════════════════════════════════════${NC}"; echo -e "${C_BOLD}${C_MAGENTA} $1${NC}"; echo -e "${C_BOLD}${C_MAGENTA}════════════════════════════════════════${NC}\n"; }

# ============================================================
# Detect cluster mode
# ============================================================
SUPCTL="supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf"

if command -v docker >/dev/null 2>&1 && docker exec hadoop01 echo OK >/dev/null 2>&1; then
  MODE="docker"
  DEFAULT_NODE="hadoop03"
  ALL_NODES=("hadoop01" "hadoop02" "hadoop03")
elif [ -S /tmp/supervisor.sock ] && jps >/dev/null 2>&1; then
  MODE="direct"
  DEFAULT_NODE="localhost"
  ALL_NODES=("localhost")
else
  # Try remote SSH mode: read config from secrets_local.py
  REMOTE_INFO=$(python3 -c "
import os, sys
sys.path.insert(0, '$PROJ_DIR/src')
try:
    import secrets_local
except ImportError:
    sys.exit(0)
host = os.environ.get('NODE01_HOST', '')
if host and host != 'localhost':
    print(f\"{host}|{os.environ.get('NODE01_SSH_PORT','2222')}|{os.environ.get('NODE02_SSH_PORT','2223')}|{os.environ.get('NODE03_SSH_PORT','2224')}\")
" 2>/dev/null || true)
  if [ -n "$REMOTE_INFO" ]; then
    REMOTE_HOST=$(echo "$REMOTE_INFO" | cut -d'|' -f1)
    NODE01_PORT=$(echo "$REMOTE_INFO" | cut -d'|' -f2)
    NODE02_PORT=$(echo "$REMOTE_INFO" | cut -d'|' -f3)
    NODE03_PORT=$(echo "$REMOTE_INFO" | cut -d'|' -f4)
    SSH_KEY="$PROJ_DIR/deploy/config/ssh/id_rsa"
    SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no"
    [ -f "$SSH_KEY" ] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
    if ssh $SSH_OPTS -p "$NODE01_PORT" "root@$REMOTE_HOST" "echo OK" </dev/null 2>/dev/null | grep -q OK; then
      MODE="remote"
      DEFAULT_NODE="hadoop03"
      ALL_NODES=("hadoop01" "hadoop02" "hadoop03")
    fi
  fi
fi

if [ -z "${MODE:-}" ]; then
  fail "Hadoop cluster not running"
  fail "Docker: docker compose up -d  |  Direct: bash scripts/setup-hadoop-direct.sh  |  Remote: check secrets_local.py"
  exit 1
fi

# ---- helpers ----

# Remote mode: get SSH port for a node
_node_ssh_port() {
  case "$1" in
    hadoop01) echo "${NODE01_PORT:-2222}" ;;
    hadoop02) echo "${NODE02_PORT:-2223}" ;;
    hadoop03) echo "${NODE03_PORT:-2224}" ;;
    *) echo "22" ;;
  esac
}

# Remote mode: SSH to a node and execute command
_remote_ssh() {
  local node="$1"; shift
  local port=$(_node_ssh_port "$node")
  ssh $SSH_OPTS -p "$port" "root@$REMOTE_HOST" "$@" </dev/null
}

cluster_exec() {
  local node="$1"; shift
  if [ "$MODE" = "docker" ]; then
    docker exec "$node" "$@"
  elif [ "$MODE" = "remote" ]; then
    local port=$(_node_ssh_port "$node")
    local cmd=""
    for arg in "$@"; do
      printf -v q '%q' "$arg"
      cmd+=" $q"
    done
    cmd="${cmd# }"
    ssh $SSH_OPTS -p "$port" "root@$REMOTE_HOST" "$cmd" </dev/null
  else
    "$@"
  fi
}

supervisor_action() {
  local node="$1" action="$2" program="$3"
  if [ "$MODE" = "docker" ]; then
    docker exec "$node" supervisorctl "$action" "$program"
  elif [ "$MODE" = "remote" ]; then
    local port=$(_node_ssh_port "$node")
    local sup_conf="/etc/supervisor/conf.d/supervisord-${node}.conf"
    ssh $SSH_OPTS -p "$port" "root@$REMOTE_HOST" "supervisorctl -c $sup_conf $action $program 2>&1" </dev/null
  else
    $SUPCTL "$action" "$program"
  fi
}

get_jps() {
  local node="$1"
  if [ "$MODE" = "docker" ]; then
    docker exec "$node" jps 2>/dev/null
  elif [ "$MODE" = "remote" ]; then
    local port=$(_node_ssh_port "$node")
    ssh $SSH_OPTS -p "$port" "root@$REMOTE_HOST" "jps 2>/dev/null" </dev/null
  else
    /usr/bin/jps 2>/dev/null
  fi
}

hdfs_cmd() {
  if [ "$MODE" = "docker" ]; then
    docker exec hadoop01 bash -c "export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64; /opt/hadoop/bin/hdfs $*"
  elif [ "$MODE" = "remote" ]; then
    local port=$(_node_ssh_port "hadoop01")
    ssh $SSH_OPTS -p "$port" "root@$REMOTE_HOST" "export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64; /opt/hadoop/bin/hdfs $*" </dev/null
  else
    /opt/hadoop/bin/hdfs "$@"
  fi
}

verify_stopped() {
  local node="$1" pattern="$2" label="$3"
  sleep 3
  local cnt
  cnt=$(get_jps "$node" | grep -c "$pattern" || true)
  if [ "$cnt" -eq 0 ]; then ok "$label stopped on $node"; else warn "$label may still be running (jps=$cnt)"; fi
}

# ---- agent url ----
agent_url() {
  if [ -f /workspace/tunnel_url.txt ]; then cat /workspace/tunnel_url.txt; else echo "http://127.0.0.1:8000"; fi
}

# ============================================================
# Fault injectors
# ============================================================

inject_datanode_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: DataNode STOP on $node"
  log "Stopping DataNode on $node..."
  supervisor_action "$node" stop datanode 2>/dev/null || true
  verify_stopped "$node" "DataNode" "DataNode"
}

inject_regionserver_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: HBase RegionServer STOP on $node"
  log "Stopping HBase RegionServer on $node..."
  supervisor_action "$node" stop regionserver 2>/dev/null || true
  verify_stopped "$node" "HRegionServer" "HRegionServer"
}

inject_zookeeper_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: ZooKeeper STOP on $node"
  log "Stopping ZooKeeper on $node..."
  supervisor_action "$node" stop zookeeper 2>/dev/null || true
  verify_stopped "$node" "QuorumPeerMain" "ZooKeeper"
}

inject_nodemanager_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: NodeManager STOP on $node"
  log "Stopping YARN NodeManager on $node..."
  supervisor_action "$node" stop nodemanager 2>/dev/null || true
  verify_stopped "$node" "NodeManager" "NodeManager"
}

inject_hiveserver2_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: HiveServer2 STOP on $node"
  log "Stopping HiveServer2 on $node..."
  supervisor_action "$node" stop hiveserver2 2>/dev/null || true
  verify_stopped "$node" "HiveServer2" "HiveServer2"
}

inject_hiveserver2_oom() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: HiveServer2 OOM on $node"

  log "Step 1: Verify HS2 is running..."
  local sup_status pid
  sup_status=$(supervisor_action "$node" status hiveserver2 2>/dev/null | awk '{print $2}' || echo "UNKNOWN")
  if [ "$sup_status" != "RUNNING" ]; then
    warn "HiveServer2 is $sup_status (not RUNNING), cannot inject OOM"
    return 1
  fi
  pid=$(cluster_exec "$node" bash -c "ps aux | grep -v grep | grep hiveserver2 | awk '{print \$2}' | head -1" | tr -d '\r\n ')
  ok "HiveServer2 RUNNING (PID: $pid)"

  log "Step 2: Deploy JDBC client tools to container..."
  # Upload HiveOOMTrigger.java and compile it inside the container
  local script_dir="$PROJ_DIR/scripts"
  if [ -f "$script_dir/HiveOOMTrigger.java" ]; then
    if [ "$MODE" = "docker" ]; then
      docker cp "$script_dir/HiveOOMTrigger.java" "$node:/tmp/HiveOOMTrigger.java"
      docker cp "$script_dir/HiveQuery.java" "$node:/tmp/HiveQuery.java" 2>/dev/null || true
    elif [ "$MODE" = "remote" ]; then
      local port=$(_node_ssh_port "$node")
      scp $SSH_OPTS -P "$port" "$script_dir/HiveOOMTrigger.java" "root@$REMOTE_HOST:/tmp/HiveOOMTrigger.java"
      scp $SSH_OPTS -P "$port" "$script_dir/HiveQuery.java" "root@$REMOTE_HOST:/tmp/HiveQuery.java" 2>/dev/null || true
    else
      cp "$script_dir/HiveOOMTrigger.java" /tmp/HiveOOMTrigger.java
      cp "$script_dir/HiveQuery.java" /tmp/HiveQuery.java 2>/dev/null || true
    fi
  fi
  cluster_exec "$node" bash -c 'cd /tmp && /usr/lib/jvm/java-21-openjdk-amd64/bin/javac HiveOOMTrigger.java 2>&1 && /usr/lib/jvm/java-21-openjdk-amd64/bin/javac HiveQuery.java 2>&1 || true'

  log "Step 3: Ensure test data exists..."
  cluster_exec "$node" bash -c '
    export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
    export HADOOP_HOME=/opt/hadoop
    /opt/hadoop/bin/hdfs dfs -test -d /user/hive/warehouse/aiopstest.db/bigdata_ext 2>/dev/null || {
      echo "Generating 2M row CSV..."
      seq 1 2000000 | awk -F, '\''BEGIN{OFS=","}{print $1, "user_"$1, "data_payload_"$1"_padding_xxxxx"}'\'' > /tmp/bigdata.csv
      /opt/hadoop/bin/hdfs dfs -mkdir -p /user/hive/warehouse/aiopstest.db/bigdata_ext
      /opt/hadoop/bin/hdfs dfs -put -f /tmp/bigdata.csv /user/hive/warehouse/aiopstest.db/bigdata_ext/
    }
    # Create database/table via JDBC (bypasses broken beeline)
    CP="$HADOOP_HOME/etc/hadoop:$HADOOP_HOME/share/hadoop/common/lib/*:$HADOOP_HOME/share/hadoop/common/*:/opt/hive/lib/*"
    $JAVA_HOME/bin/java --enable-preview --enable-native-access=ALL-UNNAMED \
      --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED \
      --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
      --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED \
      --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
      --add-opens java.base/java.io=ALL-UNNAMED \
      -cp "/tmp:$CP" HiveQuery "CREATE DATABASE IF NOT EXISTS aiopstest" 2>/dev/null || true
    $JAVA_HOME/bin/java --enable-preview --enable-native-access=ALL-UNNAMED \
      --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED \
      --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
      --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED \
      --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
      --add-opens java.base/java.io=ALL-UNNAMED \
      -cp "/tmp:$CP" HiveQuery "CREATE EXTERNAL TABLE IF NOT EXISTS aiopstest.bigdata_ext (id int, name string, payload string) ROW FORMAT DELIMITED FIELDS TERMINATED BY \",\" STORED AS TEXTFILE LOCATION \"/user/hive/warehouse/aiopstest.db/bigdata_ext\"" 2>/dev/null || true
  '

  log "Step 4: Launch concurrent JOIN queries in local MR mode..."
  log "  (No heap change, no restart — pure query-driven OOM on 512MB HS2)"
  log "  Local MR mode → JOIN runs inside HS2 JVM → hash tables in HS2 heap"
  cluster_exec "$node" bash -c '
    export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
    export HADOOP_HOME=/opt/hadoop
    export HIVE_HOME=/opt/hive
    CP="$HADOOP_HOME/etc/hadoop:$HADOOP_HOME/share/hadoop/common/lib/*:$HADOOP_HOME/share/hadoop/common/*:$HIVE_HOME/lib/*"
    timeout 180 $JAVA_HOME/bin/java \
      --enable-preview --enable-native-access=ALL-UNNAMED \
      --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED \
      --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
      --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED \
      --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
      --add-opens java.base/java.io=ALL-UNNAMED \
      -cp "/tmp:$CP" \
      HiveOOMTrigger 10 \
      2>&1 || true
  ' 2>/dev/null || true

  sleep 3
  log "Step 5: Check HS2 status and OOM evidence..."
  local sup_status_after
  sup_status_after=$(supervisor_action "$node" status hiveserver2 2>/dev/null | awk '{print $2}' || echo "UNKNOWN")

  # Check OOM in the normal HS2 log (not a separate file)
  local oom_evidence
  oom_evidence=$(cluster_exec "$node" bash -c "grep -i 'OutOfMemory\|oom.*heap\|GC overhead' /logs/hs2.log | tail -10" 2>/dev/null || true)
  if [ -n "$oom_evidence" ]; then
    ok "HiveServer2 OOM triggered on 512MB heap!"
    echo "$oom_evidence" | while read -r line; do log "  $line"; done
    if [ "$sup_status_after" != "RUNNING" ]; then
      warn "HS2 is $sup_status_after (supervisor should auto-restart)"
    else
      log "HS2 recovered (supervisor restarted it)"
    fi
  else
    warn "No OOM evidence in /logs/hs2.log"
    log "HS2 status: $sup_status_after"
    log "Agent should still detect the heavy query load and investigate"
  fi
}

inject_hbase_master_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: HBase Master STOP on $node"
  log "Stopping HBase Master on $node..."
  supervisor_action "$node" stop hmaster 2>/dev/null || true
  verify_stopped "$node" "HMaster" "HBase Master"
}

inject_resourcemanager_stop() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: YARN ResourceManager STOP on $node"
  log "Stopping ResourceManager on $node..."
  supervisor_action "$node" stop resourcemanager 2>/dev/null || true
  verify_stopped "$node" "ResourceManager" "ResourceManager"
}

inject_hdfs_safemode() {
  header "Inject: HDFS Safe Mode ON"
  log "Entering HDFS safe mode manually..."
  hdfs_cmd dfsadmin -safemode enter 2>/dev/null || true
  sleep 3
  local state
  state=$(hdfs_cmd dfsadmin -safemode get 2>/dev/null | grep -o "Safe mode is ON" || true)
  if [ -n "$state" ]; then ok "HDFS is in safe mode"; else warn "HDFS may not be in safe mode"; fi
}

inject_hdfs_corrupt() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: HDFS Corrupt Blocks"
  log "Creating test files and deleting block replicas to simulate corruption..."

  local i
  for i in 1 2 3; do
    log "  Writing test file /tmp/corrupt_test_$i..."
    cluster_exec hadoop01 bash -c "echo 'corrupt_test_data_$i' | /opt/hadoop/bin/hdfs dfs -put - -f /tmp/corrupt_test_$i" 2>/dev/null || true
  done

  local dn_dir="/data/hadoop/hdfs/datanode/current/BP-*/current/finalized/subdir0/subdir0"
  log "  Deleting block files on $node to simulate corruption..."
  if [ "$MODE" = "docker" ] || [ "$MODE" = "remote" ]; then
    cluster_exec "$node" bash -c "find $dn_dir -name 'blk_*' -type f 2>/dev/null | head -5 | xargs rm -f" 2>/dev/null || true
  else
    find $dn_dir -name 'blk_*' -type f 2>/dev/null | head -5 | xargs rm -f 2>/dev/null || true
  fi

  sleep 3
  log "  Running HDFS fsck to check corruption..."
  hdfs_cmd fsck / 2>/dev/null | grep -i "corrupt\|missing\|under replicated" | head -10 || true
  ok "Corrupt blocks injected (check via: hdfs fsck / | grep Corrupt)"
}

inject_disk_fill() {
  local node="${1:-$DEFAULT_NODE}"
  header "Inject: Disk Usage High on $node"
  log "Creating large temp files to fill disk..."

  local target_dir="/tmp"
  local before
  if [ "$MODE" = "docker" ] || [ "$MODE" = "remote" ]; then
    before=$(cluster_exec "$node" df -h / | awk 'NR==2{print $5}')
  else
    before=$(df -h / | awk 'NR==2{print $5}')
  fi
  log "  Current disk usage: $before"

  log "  Creating 2GB temp file..."
  if [ "$MODE" = "docker" ] || [ "$MODE" = "remote" ]; then
    cluster_exec "$node" bash -c "dd if=/dev/zero of=${target_dir}/disk_fill_test bs=1M count=2048 2>/dev/null" || true
  else
    dd if=/dev/zero of="${target_dir}/disk_fill_test" bs=1M count=2048 2>/dev/null || true
  fi

  local after
  if [ "$MODE" = "docker" ] || [ "$MODE" = "remote" ]; then
    after=$(cluster_exec "$node" df -h / | awk 'NR==2{print $5}')
  else
    after=$(df -h / | awk 'NR==2{print $5}')
  fi
  ok "Disk usage: $before → $after"
  log "  Cleanup: rm -f ${target_dir}/disk_fill_test (Agent should detect and clean up)"
}

# ============================================================
# Menu
# ============================================================
FAULT_NAMES=(
  "datanode_stop       Stop a DataNode"
  "regionserver_stop   Stop HBase RegionServer"
  "zookeeper_stop      Stop ZooKeeper"
  "nodemanager_stop    Stop YARN NodeManager"
  "hiveserver2_stop    Stop HiveServer2"
  "hiveserver2_oom     HiveServer2 OOM (memory stress + heavy query)"
  "hbase_master_stop   Stop HBase Master"
  "resourcemanager_stop Stop YARN ResourceManager"
  "hdfs_safemode       Force HDFS safe mode ON"
  "hdfs_corrupt        Create corrupt HDFS blocks"
  "disk_fill           Fill disk to trigger usage alert"
)

FAULT_FUNCS=(
  inject_datanode_stop
  inject_regionserver_stop
  inject_zookeeper_stop
  inject_nodemanager_stop
  inject_hiveserver2_stop
  inject_hiveserver2_oom
  inject_hbase_master_stop
  inject_resourcemanager_stop
  inject_hdfs_safemode
  inject_hdfs_corrupt
  inject_disk_fill
)

show_menu() {
  header "Fault Injection Menu  ($MODE mode, node=$DEFAULT_NODE)"
  local i=1
  for name in "${FAULT_NAMES[@]}"; do
    printf "  ${C_BOLD}%2d)${NC} %s\n" "$i" "$name"
    ((i++))
  done
  echo ""
  echo -e "  ${C_BOLD} 0)${NC} Exit"
  echo ""
}

select_node() {
  if [ "$MODE" = "direct" ]; then
    echo "localhost"
    return
  fi
  # Accept available nodes as arguments; default to ALL_NODES
  local available_nodes=(${@:-${ALL_NODES[*]}})
  local default_for_menu="${available_nodes[0]}"

  # Auto-select if only one node available
  if [ ${#available_nodes[@]} -eq 1 ]; then
    log "Auto-selecting node: ${available_nodes[0]}"
    echo "${available_nodes[0]}"
    return
  fi

  # Docker / Remote: ask which node
  # NOTE: all prompts go to stderr so stdout only returns the chosen node name
  {
    echo ""
    echo "  Select target node:"
    local i=1
    for n in "${available_nodes[@]}"; do
      printf "  ${C_BOLD}%d)${NC} %s\n" "$i" "$n"
      ((i++))
    done
    echo -e "  ${C_BOLD}0)${NC} Use default ($default_for_menu)"
    echo ""
  } >&2
  local choice
  read -rp "  Choice [0]: " choice
  if [ -z "$choice" ] || [ "$choice" = "0" ]; then
    echo "$default_for_menu"
  elif [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#available_nodes[@]}" ]; then
    echo "${available_nodes[$((choice-1))]}"
  else
    # Allow typing node name directly (e.g. "hadoop03")
    local match=""
    for n in "${available_nodes[@]}"; do
      [ "$n" = "$choice" ] && match="$n" && break
    done
    echo "${match:-$default_for_menu}"
  fi
}

# Get valid nodes for a fault type (based on supervisord configs)
# hadoop01: all services  |  hadoop02: no JHS  |  hadoop03: ZK+JN+DN+NM+RS only
_fault_nodes() {
  local func="$1"
  case "$func" in
    inject_hiveserver2_stop|inject_hiveserver2_oom|inject_hbase_master_stop|inject_resourcemanager_stop)
      echo "hadoop01 hadoop02"
      ;;
    *)
      echo "${ALL_NODES[*]}"
      ;;
  esac
}

run_inject() {
  local idx="$1"
  local func="${FAULT_FUNCS[$((idx-1))]}"
  local node

  # Faults that don't need a node
  case "$func" in
    inject_hdfs_safemode)
      $func
      ;;
    *)
      local available_nodes
      available_nodes=$(_fault_nodes "$func")
      node=$(select_node $available_nodes)
      $func "$node"
      ;;
  esac
}

# ============================================================
# Main loop
# ============================================================
header "AIOps Fault Injection Tool"
log "Cluster mode: $MODE"
if [ "$MODE" = "direct" ]; then
  log "Single-node install"
else
  log "Nodes: ${ALL_NODES[*]}"
  log "Default fault target: $DEFAULT_NODE"
  [ "$MODE" = "remote" ] && log "Remote host: $REMOTE_HOST (ports: $NODE01_PORT/$NODE02_PORT/$NODE03_PORT)"
  [ "$MODE" = "docker" ] && log "Docker containers: ${ALL_NODES[*]}"
fi
echo ""

# Check agent
if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  ok "Agent is running"
else
  warn "Agent not running (fault can still be injected, but no auto-repair)"
fi

while true; do
  show_menu
  read -rp "  Select fault type [0-11]: " choice

  if [ -z "$choice" ] || [ "$choice" = "0" ]; then
    log "Bye!"
    exit 0
  fi

  if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#FAULT_FUNCS[@]}" ]; then
    warn "Invalid choice: $choice"
    continue
  fi

  # Inject
  run_inject "$choice"

  # Wait for user to observe, then back to main menu
  echo ""
  log "Fault injected. Watch Agent activity in the web console:"
  echo -e "  ${C_BOLD}$(agent_url)${NC}"
  echo ""
  read -rp "Press Enter to continue..."
done
