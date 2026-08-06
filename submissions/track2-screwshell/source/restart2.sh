#!/bin/bash
# restart2.sh — clean relaunch of the gateway stack (clears pycache first)
cd /workspace/persistent/screwshell_run
# stop current cli-managed stack
pkill -f 'screwshell.gateway.cli' 2>/dev/null
pkill -f 'screwshell.gateway.relay' 2>/dev/null
pkill -f 'llama.cpp/build/bin/llama-server' 2>/dev/null
sleep 4
# clear stale bytecode
find screwshell -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
# relaunch via cli
setsid bash run_gateway.sh > _e2e_evidence/cli_bringup2.log 2>&1 < /dev/null &
echo "relaunched pid=$!"
