#!/bin/bash
# =============================================================================
# OmniKernel-ROCm — Demo Runner Script
# Launches the agent against the signature demo case for recording.
# =============================================================================

set -euo pipefail

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

LLM_URL="${LLM_URL:-http://localhost:8000/v1}"
LLM_MODEL="${LLM_MODEL:-qwen2.5-coder-7b-instruct}"
CODEBASE="${CODEBASE:-./cases}"
MOCK="${MOCK:-}"

echo "=============================================="
echo "  OmniKernel-ROCm — Demo Session"
echo "  LLM: $LLM_URL  |  Model: $LLM_MODEL"
echo "  Codebase: $CODEBASE"
echo "=============================================="

if [ -n "$MOCK" ]; then
    echo "  [MOCK MODE — no real GPU required]"
    python3 -m src.main \
        --codebase "$CODEBASE" \
        --mock \
        --mock-llm
else
    python3 -m src.main \
        --codebase "$CODEBASE" \
        --llm-url "$LLM_URL" \
        --llm-model "$LLM_MODEL"
fi
