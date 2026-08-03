#!/bin/bash
# aiQuant Start Script
cd "$(dirname "$0")/.."

# Configure LLM endpoint
export LLM_API_BASE=${LLM_API_BASE:-http://localhost:8000/v1}
export LLM_API_KEY=${LLM_API_KEY:-EMPTY}
export LLM_MODEL=${LLM_MODEL:-Qwen/Qwen2.5-7B-Instruct}
export RUN_MODE=local

echo "Starting aiQuant..."
echo "LLM API: $LLM_API_BASE"
echo "Model:   $LLM_MODEL"

cd src && bash start.sh
