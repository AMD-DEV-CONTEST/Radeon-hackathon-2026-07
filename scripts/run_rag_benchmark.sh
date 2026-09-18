#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/app.yaml}"
buildguard benchmark-suite --config "$CONFIG_PATH" --section rag
