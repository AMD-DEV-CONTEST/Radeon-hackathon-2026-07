#!/usr/bin/env bash

export BG_PVC=/workspace/persistent
export BG_ROOT=$BG_PVC/buildguard
export BG_REPO=$BG_ROOT/source/BuildGuard-Radeon-restored

export BG_ENVS=$BG_ROOT/envs
export BG_MODELS=$BG_ROOT/models
export BG_DATASETS=$BG_ROOT/datasets
export BG_WORKSPACE=$BG_ROOT/workspace
export BG_RUNTIME=$BG_ROOT/runtime
export BG_WHEELS=$BG_RUNTIME/wheels
export BG_LOGS=$BG_ROOT/logs
export BG_RUN=$BG_ROOT/run
export BG_ARTIFACTS=$BG_ROOT/artifacts
export BG_REPORTS=$BG_ROOT/reports
export BG_BACKUPS=$BG_ROOT/backups

export BG_MODEL_FILE=$BG_MODELS/llm/qwen3-14b-q8/Qwen3-14B-Q8_0.gguf

export BG_LLAMA_SERVER=$(
  find "$BG_RUNTIME/llama.cpp/rocm-7.2.1" \
    -type f -name llama-server \
    -print -quit
)

if [ -n "$BG_LLAMA_SERVER" ]; then
  export BG_LLAMA_LIB_DIR
  BG_LLAMA_LIB_DIR=$(dirname "$BG_LLAMA_SERVER")
  export LD_LIBRARY_PATH="$BG_LLAMA_LIB_DIR:$BG_LLAMA_LIB_DIR/lib:${LD_LIBRARY_PATH:-}"
fi

export BUILDGUARD_LLM__MODE=local
export BUILDGUARD_LLM__ENDPOINT=http://127.0.0.1:8080/v1
export BUILDGUARD_LLM__MODEL=Qwen3-14B-Q8_0.gguf
export BUILDGUARD_LLM__TIMEOUT_SECONDS=180
export BUILDGUARD_LLM__MAX_TOKENS=1024
export BUILDGUARD_LLM__TEMPERATURE=0.2
export BUILDGUARD_LLM__RETRY_ATTEMPTS=2
export BUILDGUARD_LLM__RETRY_WAIT_SECONDS=0.2

cd "$BG_REPO"
source "$BG_ENVS/app-py312-rocm721/bin/activate"
