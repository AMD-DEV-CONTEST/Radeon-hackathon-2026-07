#!/usr/bin/env python3
"""Generate Hive SQL to OOM HMS (256MB heap).
Strategy: Create 10000+ unique partitions via ALTER TABLE ADD IF NOT EXISTS.
Each partition metadata object in HMS JVM costs ~5-10KB with object overhead.
10000 partitions * 10KB = ~100MB, combined with JVM baseline ~80MB -> OOM at 256MB."""

lines = []
lines.append("CREATE DATABASE IF NOT EXISTS aiopstest;")
lines.append("USE aiopstest;")
lines.append("DROP TABLE IF EXISTS bigpart;")
lines.append("CREATE TABLE bigpart (id int, data string) PARTITIONED BY (p1 string, p2 string) STORED AS TEXTFILE;")

# Generate 10000 unique partitions using sequential keys
for i in range(1, 10001):
    p1 = f"batch{(i // 1000):02d}"
    p2 = f"item{i:06d}"
    lines.append(f"ALTER TABLE bigpart ADD IF NOT EXISTS PARTITION (p1='{p1}', p2='{p2}');")

# Final query: force HMS to load ALL partition metadata at once
lines.append("SHOW PARTITIONS bigpart;")

with open("/tmp/hive_stress3.sql", "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Generated {len(lines)} SQL statements -> /tmp/hive_stress3.sql")
