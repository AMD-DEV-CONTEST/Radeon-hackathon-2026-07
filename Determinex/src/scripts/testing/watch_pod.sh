#!/usr/bin/env bash
# Determinex RunPod Live Monitor
# Watches GPU, memory, disk, process status, and training log tail.

POD_IP="<POD_IP>"
POD_PORT="10001"
SSH_KEY="$HOME/.ssh/id_runpod"
SSH="ssh -p $POD_PORT -i $SSH_KEY -o StrictHostKeyChecking=no root@$POD_IP"

while true; do
    clear
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║          DETERMINEX RUNPOD MONITOR  —  $(date '+%Y-%m-%d %H:%M:%S')          ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"

    $SSH "
        echo ''
        echo '── GPU ──────────────────────────────────────────────────────────'
        nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu \
            --format=csv,noheader,nounits | \
            awk -F', ' '{printf \"  %-25s  GPU:%3d%%  VRAM:%5dMB/%5dMB  Temp:%d°C\n\",\$1,\$2,\$3,\$4,\$5}'

        echo ''
        echo '── DISK ─────────────────────────────────────────────────────────'
        df -h /workspace / 2>/dev/null | awk 'NR>1 {printf \"  %-40s  %s used of %s  (%s)\n\",\$6,\$3,\$2,\$5}'

        echo ''
        echo '── PROCESS ──────────────────────────────────────────────────────'
        PROC=\$(ps aux | grep -E 'dsl_finetune|run_rank4' | grep -v grep | head -3)
        if [ -z \"\$PROC\" ]; then
            echo '  No training process running.'
        else
            echo \"\$PROC\" | awk '{printf \"  PID:%-7s CPU:%-5s MEM:%-5s %s\n\",\$2,\$3,\$4,substr(\$0,index(\$0,\$11))}'
        fi

        echo ''
        echo '── STAGE ────────────────────────────────────────────────────────'
        STAGE=\$(grep -E 'STAGE|^---' /workspace/rank4_master.log 2>/dev/null | tail -6)
        echo \"\${STAGE:-  (no stage data yet)}\" | sed 's/^/  /'

        echo ''
        echo '── TRAINING LOG (last 15 lines) ─────────────────────────────────'
        # Pick whichever model log is being written right now
        ACTIVE_LOG=\$(ls -t /workspace/rank4_eng.log /workspace/rank4_obs.log /workspace/rank4_sen.log 2>/dev/null | head -1)
        if [ -n \"\$ACTIVE_LOG\" ]; then
            echo \"  [\$ACTIVE_LOG]\"
            grep -E \"loss|epoch|STAGE|DONE|FAIL|Training|Adapter|GGUF|Error\" \"\$ACTIVE_LOG\" 2>/dev/null | tail -15 | sed 's/^/  /'
        else
            echo '  (logs not yet created)'
        fi

        echo ''
        echo '── OUTPUTS ──────────────────────────────────────────────────────'
        for d in determinex-engineer-v10 determinex-observer-v5 determinex-sentinel-v4-dsl; do
            GGUF=\"/workspace/outputs/\$d/\$(ls /workspace/outputs/\$d/*.gguf 2>/dev/null | xargs -I{} basename {})\"
            SIZE=\$(du -sh /workspace/outputs/\$d/*.gguf 2>/dev/null | awk '{print \$1}')
            if [ -n \"\$SIZE\" ]; then
                printf '  %-45s  %s\n' \"\$d\" \"\$SIZE\"
            else
                printf '  %-45s  (not ready)\n' \"\$d\"
            fi
        done
    " 2>/dev/null || echo "  SSH connection failed — retrying in 10s..."

    echo ""
    echo "  Refreshes every 15s. Ctrl+C to exit."
    sleep 15
done
