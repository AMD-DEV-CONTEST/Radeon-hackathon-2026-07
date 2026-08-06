#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/app.yaml}"

python -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
python -m pip check
buildguard validate-config --config "$CONFIG_PATH"
buildguard probe-environment --config "$CONFIG_PATH"
