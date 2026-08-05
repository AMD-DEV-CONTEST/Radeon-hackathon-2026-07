#!/usr/bin/env python3
"""Generate Hive SQL to stress-test HMS/HS2 memory (256MB heap)."""
import sys

lines = []
lines.append("CREATE DATABASE IF NOT EXISTS aiopstest;")
lines.append("USE aiopstest;")

# Phase 1: Create partitioned table and add many partitions
# 31 days * 24 hours = 744 partitions, each with INSERT
lines.append("DROP TABLE IF EXISTS bigpart;")
lines.append("CREATE TABLE bigpart (id int, data string) PARTITIONED BY (dt string, hr string) STORED AS TEXTFILE;")

for d in range(1, 32):
    for h in range(0, 24):
        lines.append(f"INSERT INTO bigpart PARTITION (dt='2024-01-{d:02d}', hr='{h:02d}') VALUES ({d*100+h}, 'data_{d}_{h}');")

# Phase 2: Run a query that scans all partitions (forces HMS to load all metadata)
lines.append("SELECT COUNT(*) AS total_rows FROM bigpart;")
lines.append("SHOW PARTITIONS bigpart;")

# Phase 3: Cross join to stress HS2 result buffering
lines.append("SELECT COUNT(*) FROM bigpart a CROSS JOIN bigpart b;")

with open("/tmp/hive_stress.sql", "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Generated {len(lines)} SQL statements -> /tmp/hive_stress.sql")
