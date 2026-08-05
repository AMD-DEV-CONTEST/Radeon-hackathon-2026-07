#!/bin/bash
# Generate large CSV data and load to HDFS, then run Hive queries to trigger OOM
set -e
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

echo "=== Step 1: Generate 5M row CSV (~300MB) ==="
seq 1 5000000 | awk -F, 'BEGIN{OFS=","}{print $1, "user_"$1, "data_payload_"$1"_padding_xxxxxxxxxxxxxxxxxxxxxx"}' > /tmp/bigdata.csv
wc -l /tmp/bigdata.csv
ls -lh /tmp/bigdata.csv

echo "=== Step 2: Upload to HDFS ==="
/opt/hadoop/bin/hdfs dfs -mkdir -p /user/hive/warehouse/aiopstest.db/bigdata_ext
/opt/hadoop/bin/hdfs dfs -put -f /tmp/bigdata.csv /user/hive/warehouse/aiopstest.db/bigdata_ext/

echo "=== Step 3: Create external table and run SELECT COUNT ==="
/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false << 'BEELINE_EOF'
USE aiopstest;
DROP TABLE IF EXISTS bigdata_ext;
CREATE EXTERNAL TABLE bigdata_ext (id int, name string, payload string)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION '/user/hive/warehouse/aiopstest.db/bigdata_ext';
SELECT COUNT(*) FROM bigdata_ext;
BEELINE_EOF

echo "=== Step 4: Run SELECT * (no LIMIT) to buffer all results in HS2 ==="
/opt/hive/bin/beeline -u "jdbc:hive2://hadoop01:10000" -n root --color=false --maxWidth=200 << 'BEELINE_EOF2'
USE aiopstest;
SELECT * FROM bigdata_ext;
BEELINE_EOF2

echo "=== Done ==="
