#!/bin/bash
cd /workspace/forgearena
export GRADIO_SERVER_PORT=9876
nohup python3 -u forgearena_ui_v2.py > /tmp/ui_v2_final.log 2>&1 &
PID=$!
echo $PID > /tmp/forgearena_ui.pid
echo "Started PID: $PID"
