#!/usr/bin/env python3
"""Generate Hive SQL to stress-test HMS memory (256MB heap).
Uses ALTER TABLE ADD PARTITION (no Tez needed) to create thousands of partitions."""
import sys

lines = []
lines.append("CREATE DATABASE IF NOT EXISTS aiopstest;")
lines.append("USE aiopstest;")
lines.append("DROP TABLE IF EXISTS bigpart;")
lines.append("CREATE TABLE bigpart (id int, data string) PARTITIONED BY (dt string, hr string) STORED AS TEXTFILE;")

# Add 2000 partitions via ALTER TABLE (no Tez needed, pure HMS metadata operation)
# Each partition adds ~1-2KB of metadata to HMS heap
for i in range(1, 2001):
    dt = f"2024-{(i // 100) + 1:02d}-{(i % 100) + 1:02d}"
    if int((i % 100) + 1) > 28:
        dt = f"2024-12-{(i % 28) + 1:02d}"
    hr = f"{i % 24:02d}"
    lines.append(f"ALTER TABLE bigpart ADD PARTITION (dt='{dt}', hr='{hr}');")

# Query that forces HMS to load ALL partition metadata at once
lines.append("SHOW PARTITIONS bigpart;")
lines.append("SELECT COUNT(*) FROM bigpart;")

with open("/tmp/hive_stress2.sql", "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Generated {len(lines)} SQL statements -> /tmp/hive_stress2.sql")
