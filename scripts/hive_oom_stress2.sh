#!/bin/bash
# Generate large CSV data and load to HDFS, then run Hive queries to trigger OOM
set -e
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export TERM=dumb

echo "=== Step 1: Generate 5M row CSV (~300MB) ==="
seq 1 5000000 | awk -F, 'BEGIN{OFS=","}{print $1, "user_"$1, "data_payload_"$1"_padding_xxxxxxxxxxxxxxxxxxxxxx"}' > /tmp/bigdata.csv
wc -l /tmp/bigdata.csv
ls -lh /tmp/bigdata.csv

echo "=== Step 2: Upload to HDFS ==="
/opt/hadoop/bin/hdfs dfs -mkdir -p /user/hive/warehouse/aiopstest.db/bigdata_ext
/opt/hadoop/bin/hdfs dfs -put -f /tmp/bigdata.csv /user/hive/warehouse/aiopstest.db/bigdata_ext/

echo "=== Step 3: Create external table ==="
cat > /tmp/hive_create.sql << 'SQLEOF'
USE aiopstest;
DROP TABLE IF EXISTS bigdata_ext;
CREATE EXTERNAL TABLE bigdata_ext (id int, name string, payload string)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION '/user/hive/warehouse/aiopstest.db/bigdata_ext';
SELECT COUNT(*) AS cnt FROM bigdata_ext;
SQLEOF

/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false -f /tmp/hive_create.sql 2>&1 | tail -20

echo "=== Step 4: Run SELECT * (no LIMIT) to buffer all results in HS2 ==="
cat > /tmp/hive_select_all.sql << 'SQLEOF2'
USE aiopstest;
SELECT * FROM bigdata_ext;
SQLEOF2

/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false -f /tmp/hive_select_all.sql 2>&1 | tail -30

echo "=== Done ==="
