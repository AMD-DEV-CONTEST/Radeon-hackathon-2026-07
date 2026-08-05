#!/bin/bash
SSH_KEY=/workspace/Radeon-hackathon-2026-07/deploy/config/ssh/id_rsa
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i $SSH_KEY"

# Test: ssh -tt (force pseudo-tty allocation)
echo "=== Test: ssh -tt ==="
ssh -tt $SSH_OPTS -p 2222 root@8.148.228.51 'echo "SHOW DATABASES;" > /tmp/test_beeline.sql && /tmp/beeline_fixed.sh -u jdbc:hive2://localhost:10000 -n root -f /tmp/test_beeline.sql 2>&1 | tail -20'
