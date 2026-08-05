#!/bin/bash
# test_hive_queries.sh — Test various Hive queries via JDBC
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export HADOOP_HOME=/opt/hadoop
export HIVE_HOME=/opt/hive

CP="$HADOOP_HOME/etc/hadoop:$HADOOP_HOME/share/hadoop/common/lib/*:$HADOOP_HOME/share/hadoop/common/*:$HIVE_HOME/lib/*"

JAVA_OPTS="--enable-preview --enable-native-access=ALL-UNNAMED \
  --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED \
  --add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED \
  --add-opens java.base/java.util.concurrent=ALL-UNNAMED --add-opens java.base/java.util.concurrent.atomic=ALL-UNNAMED \
  --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED \
  --add-opens java.base/java.io=ALL-UNNAMED"

# Test 1: Simple fetch (no Tez)
echo "=== Test 1: SELECT * LIMIT 5 (fetch mode) ==="
$JAVA_HOME/bin/java $JAVA_OPTS -cp "/tmp:$CP" HiveQuery 'SELECT * FROM aiopstest.bigdata_ext LIMIT 5'

# Test 2: SET hive.execution.engine=mr + COUNT
echo "=== Test 2: SET engine=mr, then COUNT ==="
$JAVA_HOME/bin/java $JAVA_OPTS -cp "/tmp:$CP" HiveQuery 'SET hive.execution.engine=mr'

# Test 3: Use Mr engine for heavy query
echo "=== Test 3: Heavy query with MR engine ==="
$JAVA_HOME/bin/java $JAVA_OPTS -cp "/tmp:$CP" HiveQuery 'SET hive.execution.engine=mr; SET hive.fetch.task.conversion=none; SELECT COUNT(*) FROM aiopstest.bigdata_ext'

echo "=== Done ==="
