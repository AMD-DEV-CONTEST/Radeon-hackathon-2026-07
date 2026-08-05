#!/bin/bash
# hs2_oom_inject.sh — Inject HS2 OOM by starting with tiny heap + heavy query
# This script runs INSIDE the container (hadoop01)

set -e

SUPCONF="/etc/supervisor/conf.d/supervisord-hadoop01.conf"

echo "=== Step 1: Stop HS2 via supervisorctl ==="
supervisorctl -c $SUPCONF stop hiveserver2 2>/dev/null || true
sleep 3

echo "=== Step 2: Start HS2 with small heap (128MB) ==="
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export HADOOP_HOME=/opt/hadoop
export HIVE_HOME=/opt/hive
export HADOOP_HEAPSIZE=128
export HADOOP_OPTS="-Xmx128m -Xms128m -javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10111:/opt/jmx-exporter/config.yml --enable-preview --enable-native-access=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED"
export HIVE_CONF_DIR=$HIVE_HOME/conf

# Start HS2 in background
nohup $HIVE_HOME/bin/hiveserver2 > /logs/hs2_oom.log 2>&1 &
HS2_PID=$!
echo "HS2 started with PID $HS2_PID (heap: 128MB)"

echo "=== Step 3: Wait for HS2 to be ready ==="
for i in $(seq 1 30); do
    sleep 2
    if grep -q "HiveServer2" /logs/hs2_oom.log 2>/dev/null && \
       ! grep -q "Starting HiveServer2" /logs/hs2_oom.log 2>/dev/null; then
        echo "HS2 ready after $((i*2))s"
        break
    fi
    # Check if process is still alive
    if ! kill -0 $HS2_PID 2>/dev/null; then
        echo "HS2 process died during startup!"
        cat /logs/hs2_oom.log
        exit 1
    fi
    echo "  Waiting... ($((i*2))s)"
done

# Verify HS2 is listening
if ! ss -tlnp | grep -q 10000; then
    echo "HS2 not listening on port 10000, waiting more..."
    sleep 10
fi

echo "=== Step 4: Verify HS2 heap size ==="
ps aux | grep hiveserver2 | grep -v grep | head -1 | grep -o 'Xmx[0-9]*[mg]' | head -1

echo "=== Step 5: Run heavy query to trigger OOM ==="
CP="$HADOOP_HOME/etc/hadoop:$HADOOP_HOME/share/hadoop/common/lib/*:$HADOOP_HOME/share/hadoop/common/*:$HIVE_HOME/lib/*"

# 3 concurrent queries: SELECT * on 5M rows with 128MB heap = OOM
$JAVA_HOME/bin/java \
  --enable-preview --enable-native-access=ALL-UNNAMED \
  --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED \
  --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
  --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED \
  --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
  --add-opens java.base/java.io=ALL-UNNAMED \
  -cp "/tmp:$CP" \
  HiveOOMTrigger 3 \
  "USE aiopstest; SET hive.execution.engine=mr; SET hive.fetch.task.conversion=more; SET hive.fetch.task.conversion.threshold=100000000; SELECT * FROM bigdata_ext" \
  || true

echo "=== Step 6: Check HS2 status ==="
if kill -0 $HS2_PID 2>/dev/null; then
    echo "HS2 still running (PID $HS2_PID)"
    # Kill the manually started HS2
    kill -9 $HS2_PID 2>/dev/null || true
    echo "Killed manual HS2"
else
    echo "HS2 crashed (OOM)!"
fi

echo "=== Step 7: Check OOM evidence ==="
grep -i "OutOfMemory\|oom\|heap\|GC overhead" /logs/hs2_oom.log | tail -10 || echo "No OOM evidence found"

echo "=== Step 8: Restart HS2 via supervisorctl ==="
supervisorctl -c $SUPCONF start hiveserver2 2>/dev/null || true
echo "HS2 restart initiated (supervisor will manage it)"

echo "=== Done ==="
