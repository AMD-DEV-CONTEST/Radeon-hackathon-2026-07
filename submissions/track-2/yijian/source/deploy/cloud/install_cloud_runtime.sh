#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
LLAMA_SRC="$PERSIST_ROOT/llama.cpp"
VENV="$PERSIST_ROOT/venv"
HF_HOME="${HF_HOME:-$PERSIST_ROOT/huggingface}"
export HF_HOME

mkdir -p "$PERSIST_ROOT" "$HF_HOME" "$PERSIST_ROOT/logs" "$PERSIST_ROOT/benchmarks"
echo "[1/5] 验证 AMD ROCm 环境"
command -v amd-smi >/dev/null && amd-smi static --asic --vram --driver --bus || true
command -v rocminfo >/dev/null
rocminfo | grep -m1 -E 'gfx[0-9]+'

echo "[2/5] 建立持久 Python 环境"
if [[ ! -x "$VENV/bin/python" ]]; then python3 -m venv "$VENV"; fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$PROJECT_ROOT/requirements.txt" huggingface_hub
PLAYWRIGHT_BROWSERS_PATH="$PERSIST_ROOT/playwright" \
  "$VENV/bin/python" -m playwright install chromium

echo "[3/5] 构建 llama.cpp ROCm gfx1100 运行时"
if [[ ! -d "$LLAMA_SRC/.git" ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_SRC"
else
  git -C "$LLAMA_SRC" fetch --depth 1 origin master
  git -C "$LLAMA_SRC" checkout --detach FETCH_HEAD
fi
HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" \
  cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" \
    -DGGML_HIP=ON -DGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release
cmake --build "$LLAMA_SRC/build" --config Release --target llama-server llama-bench -- -j "$(nproc)"

echo "[4/5] 预下载 Qwen3.6-27B Q4 到持久盘"
"$VENV/bin/hf" download ggml-org/Qwen3.6-27B-GGUF \
  Qwen3.6-27B-Q4_K_M.gguf \
  --local-dir "$PERSIST_ROOT/models/qwen36"
"$VENV/bin/hf" download Qwen/Qwen3-4B-GGUF \
  --include '*Q4_K_M*' --cache-dir "$HF_HOME"

echo "[5/5] 环境完成"
echo "持久目录：$PERSIST_ROOT"
echo "下一步：bash deploy/cloud/start_cloud_stack.sh"
