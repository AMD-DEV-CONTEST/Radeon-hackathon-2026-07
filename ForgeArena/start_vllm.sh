#!/bin/bash
MODEL="/root/.cache/modelscope/models/qwen--Qwen2.5-7B-Instruct/snapshots/master"
echo "Starting vLLM with Qwen2.5-7B from: $MODEL"
vllm serve "$MODEL" --host 0.0.0.0 --port 8001 --dtype half --gpu-memory-utilization 0.85 --max-model-len 8192 --trust-remote-code --enforce-eager 2>&1 | tee /workspace/forgearena/vllm_new.log
