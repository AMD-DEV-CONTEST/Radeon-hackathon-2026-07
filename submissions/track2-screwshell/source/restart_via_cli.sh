#!/bin/bash
# restart_via_cli.sh — roll the live stack to gateway/cli.py orchestration.
set -uo pipefail
cd /workspace/persistent/screwshell_run

# 1) rollback record (PIDs captured before kill)
echo "BACKUP_PIDS llama=28166 relay=33702 ui=19466" > _e2e_evidence/rollback_info.txt
echo "ts=$(date +%FT%T)" >> _e2e_evidence/rollback_info.txt

# 2) stop the manually-launched llama-server + relay (UI on :7860 stays up)
kill 28166 33702 2>/dev/null
sleep 4

# 3) launch the whole stack via gateway/cli (setsid inside cli)
setsid bash run_gateway.sh > _e2e_evidence/cli_bringup.log 2>&1 < /dev/null &
echo "launched cli pid=$!"
