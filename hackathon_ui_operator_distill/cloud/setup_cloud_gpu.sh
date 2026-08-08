#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip

# Core training/export stack.
pip install ultralytics onnx onnxruntime onnxruntime-tools opencv-python pillow numpy pyyaml tqdm

# OmniParser dependencies are installed from the upstream repo after clone.
pip install huggingface_hub

echo "Cloud GPU setup complete."
echo "Next:"
echo "  bash cloud/download_omniparser_v2.sh"

