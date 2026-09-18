#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/app.yaml}"
export BUILDGUARD_LLM__MODE=mock
exec buildguard run-demo --config "$CONFIG_PATH"
