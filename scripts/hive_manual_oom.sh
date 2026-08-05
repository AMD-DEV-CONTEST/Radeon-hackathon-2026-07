#!/bin/bash
# Stop HS2 via supervisord, start manually with 128MB heap, trigger OOM
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export TERM=dumb

echo "=== Step 1: Stop HS2 via supervisord ==="
supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf stop hiveserver2

echo "=== Step 2: Start HS2 manually with 128MB heap ==="
# Override HADOOP_HEAPSIZE_MAX to force 128MB heap
export HADOOP_HEAPSIZE=128
export HADOOP_HEAPSIZE_MAX=128
# Keep the JMX exporter agent
export HADOOP_OPTS="-javaagent:/opt/jmx-exporter/jmx_prometheus_javaagent-0.20.0.jar=10111:/opt/jmx-exporter/config.yml -Xmx128m"
nohup /opt/hive/bin/hiveserver2 > /logs/hs2_manual.log 2>&1 &
echo "HS2 PID: $!"
sleep 10

echo "=== Step 3: Verify heap is 128MB ==="
ps aux | grep hiveserver2 | grep -v grep | grep -o '\-Xmx[0-9]*[mMgG]' | head -1

echo "=== Step 4: Test connectivity ==="
/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false -e "SELECT 1;" 2>&1 | tail -5

echo "=== Step 5: Run SELECT * on 5M row table to trigger OOM ==="
cat > /tmp/hive_oom_trigger.sql << 'SQLEOF'
USE aiopstest;
SET hive.fetch.task.conversion=none;
SELECT * FROM bigdata_ext;
SQLEOF

/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false -f /tmp/hive_oom_trigger.sql 2>&1 | tail -30

echo "=== Step 6: Check if HS2 is still alive ==="
ps aux | grep hiveserver2 | grep -v grep | wc -l
echo "HS2 processes running"

echo "=== Step 7: Check HS2 logs for OOM ==="
tail -100 /logs/hs2_manual.log 2>&1 | grep -i "oom\|OutOfMemory\|heap\|error\|killed\|exception" | tail -20
echo "---"
tail -20 /logs/hs2_manual.log 2>&1

echo "=== Done ==="
