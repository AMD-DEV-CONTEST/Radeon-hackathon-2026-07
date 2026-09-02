#!/bin/bash
# Nuclear stop — kill EVERY PB-related process (agent, handoff wrapper, monitors).
# Use any time you need to stop the world. Idempotent — safe to re-run.
#
# Usage: bash scripts/kill_all_pb.sh [--quiet]

QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

log() { [ "$QUIET" -eq 0 ] && echo "$@"; }

log "[kill_all_pb] $(date -Iseconds) — sweeping all PB processes..."

# Powershell sees Windows python processes; bash pgrep does NOT (Windows native procs).
# Match anything containing 'determinex_programbench_agent' or 'run_pb_sequence' on the command line.
powershell.exe -NoProfile -Command "
    \$killed = 0
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        \$cmd = (Get-CimInstance Win32_Process -Filter \"ProcessId=\$(\$_.Id)\" -ErrorAction SilentlyContinue).CommandLine
        if (\$cmd -like '*determinex_programbench_agent*' -or \$cmd -like '*run_pb_sequence*' -or \$cmd -like '*prepull_pb_blobs*') {
            Stop-Process -Id \$_.Id -Force -ErrorAction SilentlyContinue
            Write-Output \"  killed python PID \$(\$_.Id)\"
            \$killed++
        }
    }
    Get-Process bash -ErrorAction SilentlyContinue | ForEach-Object {
        \$cmd = (Get-CimInstance Win32_Process -Filter \"ProcessId=\$(\$_.Id)\" -ErrorAction SilentlyContinue).CommandLine
        if (\$cmd -like '*run_pb_sequence*' -or \$cmd -like '*determinex_programbench_agent*') {
            Stop-Process -Id \$_.Id -Force -ErrorAction SilentlyContinue
            Write-Output \"  killed bash PID \$(\$_.Id)\"
            \$killed++
        }
    }
    Write-Output \"[kill_all_pb] killed \$killed process(es)\"
" 2>&1 | sed 's/\r$//'

log "[kill_all_pb] done."
