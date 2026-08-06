#!/bin/bash
# 启动 A1111 WebUI（独立 venv，监听 127.0.0.1:7860）
VENV=/persistent/webui_env/bin/python
WEBUI=/workspace/stable-diffusion-webui
LOG=/tmp/webui_run.log

if pgrep -f "webui.py --skip-torch-cuda-test" > /dev/null; then
    echo "WebUI 已在运行"
else
    setsid bash -c "export ROCM_PATH=/opt/rocm HSA_OVERRIDE_GFX_VERSION=11.0.0 HF_HUB_OFFLINE=1; unset LD_LIBRARY_PATH; cd $WEBUI && exec $VENV webui.py --skip-torch-cuda-test --server-name 127.0.0.1 --port 7860 --no-half-vae --opt-sdp-attention --api > $LOG 2>&1" < /dev/null &
    echo "WebUI 启动中，日志: $LOG"
fi
