#!/bin/bash
SSH_KEY=/workspace/Radeon-hackathon-2026-07/deploy/config/ssh/id_rsa
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i $SSH_KEY"

# Fix CRLF in beeline.sh on hadoop01
echo "=== Fixing beeline.sh CRLF ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'sed -i "s/\r//g" /opt/hive/bin/ext/beeline.sh && echo FIXED'

# Test original beeline
echo "=== Testing original beeline ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 '/opt/hive/bin/beeline -u jdbc:hive2://localhost:10000 -n root -e "SHOW DATABASES" 2>&1 | tail -20'
