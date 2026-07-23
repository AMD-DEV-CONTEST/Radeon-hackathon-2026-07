#!/bin/bash
cd /workspace/forgearena
export GRADIO_SERVER_PORT=22222
exec nohup python3 -u forgearena_ui_v2.py > /tmp/ui_v2_running.log 2>&1 &
