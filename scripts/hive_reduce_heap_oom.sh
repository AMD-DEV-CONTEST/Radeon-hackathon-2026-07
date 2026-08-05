#!/bin/bash
# Reduce HS2 heap to 128MB, restart, then run heavy query to trigger OOM
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export TERM=dumb

echo "=== Step 1: Reduce HS2 heap to 128MB ==="
# Modify supervisord config to add HADOOP_HEAPSIZE_MAX=128
sed -i 's/HADOOP_HEAPSIZE="256"/HADOOP_HEAPSIZE="128",HADOOP_HEAPSIZE_MAX="128"/g' /etc/supervisor/conf.d/supervisord-hadoop01.conf
sed -i 's/HADOOP_HEAPSIZE="256"/HADOOP_HEAPSIZE="128",HADOOP_HEAPSIZE_MAX="128"/g' /etc/supervisor/conf.d/supervisord-hadoop02.conf

echo "=== Step 2: Restart HS2 on hadoop01 ==="
supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf restart hiveserver2
sleep 5
supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf status hiveserver2

echo "=== Step 3: Verify heap is 128MB ==="
ps aux | grep hiveserver2 | grep -v grep | grep -o '\-Xmx[0-9]*[mMgG]' | head -1

echo "=== Step 4: Run SELECT * on 5M row table (345MB data) ==="
cat > /tmp/hive_oom_trigger.sql << 'SQLEOF'
USE aiopstest;
SET hive.fetch.task.conversion=none;
SELECT * FROM bigdata_ext;
SQLEOF

/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false -f /tmp/hive_oom_trigger.sql 2>&1 | tail -30

echo "=== Step 5: Check HS2 status ==="
supervisorctl -c /etc/supervisor/conf.d/supervisord-hadoop01.conf status hiveserver2

echo "=== Step 6: Check HS2 logs for OOM ==="
tail -50 /logs/hs2.log 2>&1 | grep -i "oom\|OutOfMemory\|heap\|error\|killed" | tail -20

echo "=== Done ==="
