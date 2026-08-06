#!/bin/bash
source /persistent/amd_ai_env/bin/activate
cd /workspace/ComfyUI
python3 main.py --listen --port 8188
