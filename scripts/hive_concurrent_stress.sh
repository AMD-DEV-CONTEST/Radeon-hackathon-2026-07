#!/bin/bash
# Launch many concurrent beeline sessions to OOM HS2 (512MB heap)
# Each session runs a long query, keeping the HS2 session alive and consuming heap
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export TERM=dumb

echo "=== Launching 30 concurrent beeline sessions ==="

# Create SQL that takes a while (cross join on bigdata_ext)
cat > /tmp/hive_heavy.sql << 'SQLEOF'
USE aiopstest;
SET hive.execution.engine=mr;
SET mapreduce.framework.name=local;
SET hive.fetch.task.conversion=none;
SELECT a.id, b.id, concat(a.payload, b.payload) FROM bigdata_ext a JOIN bigdata_ext b ON a.id < b.id LIMIT 5000000;
SQLEOF

# Launch 30 concurrent beeline sessions
for i in $(seq 1 30); do
  echo "Starting session $i..."
  /opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false -f /tmp/hive_heavy.sql > /tmp/beeline_$i.log 2>&1 &
done

echo "=== All 30 sessions launched, waiting for OOM... ==="
echo "Monitoring HS2 status..."

# Monitor HS2 status every 10 seconds
for i in $(seq 1 30); do
  sleep 10
  STATUS=$(supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf status hiveserver2 2>&1)
  echo "[$(date +%H:%M:%S)] HS2: $STATUS"
  if echo "$STATUS" | grep -q "STOPPED\|EXITED\|FATAL"; then
    echo "!!! HS2 CRASHED !!!"
    break
  fi
done

echo "=== Checking HS2 logs for OOM ==="
tail -30 /logs/hs2.log 2>&1

echo "=== Done ==="
