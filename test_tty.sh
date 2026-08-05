#!/bin/bash
SSH_KEY=/workspace/Radeon-hackathon-2026-07/deploy/config/ssh/id_rsa
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i $SSH_KEY"

# Test 1: ssh -t (allocate pseudo-tty)
echo "=== Test 1: ssh -t with beeline -f ==="
ssh -t $SSH_OPTS -p 2222 root@8.148.228.51 'echo "SHOW DATABASES;" > /tmp/test_beeline.sql && /tmp/beeline_fixed.sh -u jdbc:hive2://localhost:10000 -n root -f /tmp/test_beeline.sql 2>&1 | tail -20'

# Test 2: Try setting JAVA_TOOL_OPTIONS
echo "=== Test 2: JAVA_TOOL_OPTIONS ==="
ssh $SSH_OPTS -p 2222 root@8.148.228.51 'export JAVA_TOOL_OPTIONS="-Djline.terminal=dumb -Djline.terminal.jansi=false"; echo "SHOW DATABASES;" > /tmp/test_beeline.sql && /tmp/beeline_fixed.sh -u jdbc:hive2://localhost:10000 -n root -f /tmp/test_beeline.sql 2>&1 | tail -20'
