#!/bin/bash
SSH_KEY=/workspace/Radeon-hackathon-2026-07/deploy/config/ssh/id_rsa
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i $SSH_KEY"

# Fix CRLF using tr (works on bind-mount files where sed -i fails)
echo "=== Fixing beeline.sh CRLF (tr method) ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'tr -d "\r" < /opt/hive/bin/ext/beeline.sh > /tmp/beeline_fixed.sh && cp /tmp/beeline_fixed.sh /opt/hive/bin/ext/beeline.sh && echo FIXED'

# Test beeline -f with a simple SQL file
echo "=== Testing beeline -f ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'echo "SHOW DATABASES;" > /tmp/test_beeline.sql && /opt/hive/bin/beeline -u jdbc:hive2://localhost:10000 -n root -f /tmp/test_beeline.sql 2>&1 | tail -20'
