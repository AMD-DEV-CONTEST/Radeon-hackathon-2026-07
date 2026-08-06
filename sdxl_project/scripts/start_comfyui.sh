#!/bin/bash
# 启动 ComfyUI（监听 127.0.0.1:8188，仅本机访问，外网需 SSH 隧道）
VENV=/persistent/amd_ai_env/bin/python
COMFY=/workspace/ComfyUI
LOG=/tmp/comfyui_run.log

if pgrep -f "main.py --listen 127.0.0.1" > /dev/null; then
    echo "ComfyUI 已在运行"
else
    setsid bash -c "export ROCM_PATH=/opt/rocm HSA_OVERRIDE_GFX_VERSION=11.0.0; cd $COMFY && exec $VENV main.py --listen 127.0.0.1 --port 8188 > $LOG 2>&1" < /dev/null &
    echo "ComfyUI 启动中，日志: $LOG"
fi
