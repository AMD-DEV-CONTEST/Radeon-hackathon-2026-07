#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${1:-/workspace/yijian/qwen3-14b-bf16}"
LOG_DIR="${2:-/workspace/yijian/lora-data-closure-v1/audits}"
mkdir -p "$MODEL_DIR" "$LOG_DIR"

/workspace/yijian-venv/bin/modelscope download Qwen/Qwen3-14B \
  config.json generation_config.json tokenizer_config.json tokenizer.json \
  vocab.json merges.txt model.safetensors.index.json \
  model-00001-of-00008.safetensors model-00002-of-00008.safetensors \
  model-00003-of-00008.safetensors model-00004-of-00008.safetensors \
  model-00005-of-00008.safetensors model-00006-of-00008.safetensors \
  model-00007-of-00008.safetensors model-00008-of-00008.safetensors \
  --local-dir "$MODEL_DIR" --max-workers 8

cd "$MODEL_DIR"
cat > "$LOG_DIR/qwen3-14b-expected-sha256.txt" <<'EOF'
e73c3664ca09b10a673fef0c22e8a6b456201d49bd4713c9691f775720e8857a  config.json
2325da0f15bb848e018c5ae071b7943332e9f871d6b60e2ed22ca97d4cb993d2  generation_config.json
d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101  tokenizer_config.json
aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4  tokenizer.json
ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910  vocab.json
8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5  merges.txt
62d7ad35757bae5e7baa452cb1483178b7daa50e869e923226b8da10871f7ebc  model.safetensors.index.json
e942bdbdf08857d16a8fef7d1dae9fceabeb4e84def6043485fe2f6f085dab0e  model-00001-of-00008.safetensors
f7c9c6eee628f5ad831d2d1d292e120505e5fcadeb38f88b4d3c4cb86306ccf9  model-00002-of-00008.safetensors
dfb8c5df9404b41ad6ae74e8b6b367135f017b4467b884cf71b17c71954f18a9  model-00003-of-00008.safetensors
eab286fec759e3e59ab228621aefa0fef14ed56039e06f959e67257d5af7604d  model-00004-of-00008.safetensors
97f0dc2992e59da95c466eff6f4fd0c8335843bbc36ed5c913a6f5150748c0e6  model-00005-of-00008.safetensors
9e8e76a013cd5e253865b792991e0b410f869b136b3c500079b531b09198e99e  model-00006-of-00008.safetensors
0aee70ee6e91dc00d818804fb47f124d13ee4ad5b4a64553e09dbf9391cd5750  model-00007-of-00008.safetensors
0d6b92296e326d39bbbaeb32c3ec454ac606da843d4c8ffa8edf010b62b8c9e0  model-00008-of-00008.safetensors
EOF

sha256sum -c "$LOG_DIR/qwen3-14b-expected-sha256.txt" | tee "$LOG_DIR/qwen3-14b-sha256-check.txt"
printf '%s\n' 'Qwen/Qwen3-14B revision 40c069824f4251a91eefaf281ebe4c544efd3e18 verified' \
  > "$LOG_DIR/qwen3-14b-download-complete.txt"
