#!/usr/bin/env bash
set -euo pipefail

if [ ! -d "OmniParser" ]; then
  git clone https://github.com/microsoft/OmniParser.git
fi

cd OmniParser
pip install -r requirements.txt

mkdir -p weights
for f in \
  icon_detect/train_args.yaml \
  icon_detect/model.pt \
  icon_detect/model.yaml \
  icon_caption/config.json \
  icon_caption/generation_config.json \
  icon_caption/model.safetensors
do
  huggingface-cli download microsoft/OmniParser-v2.0 "$f" --local-dir weights
done

if [ -d "weights/icon_caption" ] && [ ! -d "weights/icon_caption_florence" ]; then
  mv weights/icon_caption weights/icon_caption_florence
fi

echo "OmniParser v2 weights ready in OmniParser/weights."

