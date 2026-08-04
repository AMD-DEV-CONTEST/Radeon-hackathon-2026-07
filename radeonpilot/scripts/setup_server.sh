#!/usr/bin/env bash
# RadeonPilot server bootstrap — ROCm endpoint toolchain for the Radeon Cloud instance.
# Steps: Node 22, ffmpeg, python venv, Qwen3-8B download (ModelScope),
#        llama.cpp ROCm build, vLLM ROCm attempt (background).
set -uo pipefail

ROOT=/root/radeonpilot-setup
VENV=/root/radeonpilot/.venv
MODEL_DIR=/root/models/Qwen3-8B
mkdir -p "$ROOT"
LOG=$ROOT/bootstrap.log
exec > >(tee -a "$LOG") 2>&1

echo "== [1/7] Node 22 $(date -u +%FT%TZ)"
if [ ! -x /opt/node22/bin/node ] || ! /opt/node22/bin/node --version | grep -q '^v22\.'; then
  VER=$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c \
    "import json,sys; print(next(e['version'] for e in json.load(sys.stdin) if e['version'].startswith('v22.')))")
  echo "installing node $VER"
  curl -fsSL -o "$ROOT/node.tar.xz" "https://nodejs.org/dist/$VER/node-$VER-linux-x64.tar.xz"
  rm -rf /opt/node22 && mkdir -p /opt/node22
  tar -xJf "$ROOT/node.tar.xz" -C /opt/node22 --strip-components=1
  echo 'export PATH=/opt/node22/bin:$PATH' > /etc/profile.d/node22.sh
fi
/opt/node22/bin/node --version
/opt/node22/bin/npm --version

echo "== [2/7] ffmpeg $(date -u +%FT%TZ)"
command -v ffmpeg >/dev/null || { apt-get update -qq && apt-get install -y -qq ffmpeg; }
ffmpeg -version 2>/dev/null | head -1

echo "== [3/7] python venv $(date -u +%FT%TZ)"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -U pip wheel setuptools
"$VENV/bin/python" --version

echo "== [4/7] model download Qwen3-8B via ModelScope $(date -u +%FT%TZ)"
"$VENV/bin/pip" install -q modelscope
if [ ! -f "$MODEL_DIR/config.json" ]; then
  "$VENV/bin/modelscope" download --model Qwen/Qwen3-8B --local_dir "$MODEL_DIR"
fi
du -sh "$MODEL_DIR" 2>/dev/null
ls "$MODEL_DIR" | head

echo "== [5/7] llama.cpp ROCm build $(date -u +%FT%TZ)"
cd "$ROOT"
if [ ! -d llama.cpp/.git ]; then
  rm -rf llama.cpp
  for attempt in 1 2 3 4; do
    git clone --depth 1 https://github.com/ggml-org/llama.cpp && break
    echo "llama.cpp clone attempt $attempt failed, retrying..."
    sleep 5
  done
fi
if [ ! -f llama.cpp/CMakeLists.txt ]; then
  echo "FATAL: llama.cpp source unavailable" | tee -a "$LOG"
  exit 1
fi
cd llama.cpp
cmake -B build -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1100 -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build build --config Release -j 64 --target llama-server llama-cli llama-bench llama-quantize llama-gguf-split
./build/bin/llama-cli --version

echo "== [6/7] GGUF conversion (BF16 stable + Q4_K_M quantized) $(date -u +%FT%TZ)"
mkdir -p /root/models/gguf
if [ ! -f /root/models/gguf/Qwen3-8B-f16.gguf ]; then
  "$VENV/bin/pip" install -q 'transformers>=4.51' torch --extra-index-url https://download.pytorch.org/whl/cpu || \
  "$VENV/bin/pip" install -q 'transformers>=4.51' torch
  cd "$ROOT" && "$VENV/bin/python" llama.cpp/convert_hf_to_gguf.py "$MODEL_DIR" \
    --outfile /root/models/gguf/Qwen3-8B-f16.gguf --outtype f16
fi
if [ ! -f /root/models/gguf/Qwen3-8B-Q4_K_M.gguf ]; then
  cd "$ROOT/llama.cpp" && ./build/bin/llama-quantize /root/models/gguf/Qwen3-8B-f16.gguf \
    /root/models/gguf/Qwen3-8B-Q4_K_M.gguf Q4_K_M
fi
ls -lh /root/models/gguf/

echo "== [7/7] vLLM ROCm attempt (background) $(date -u +%FT%TZ)"
cat > "$ROOT/install_vllm.sh" <<'EOS'
#!/usr/bin/env bash
set -uo pipefail
V=/root/radeonpilot/.venv-vllm
python3 -m venv "$V"
"$V/bin/pip" install -U pip wheel setuptools
for IDX in rocm7.2 rocm7.0 rocm6.4; do
  echo "trying torch index $IDX"
  if "$V/bin/pip" install torch --index-url "https://download.pytorch.org/whl/$IDX"; then
    echo "torch installed from $IDX"; break
  fi
done
"$V/bin/pip" install vllm==0.26.0 && echo VLLM_INSTALL_OK || echo VLLM_INSTALL_FAILED
EOS
chmod +x "$ROOT/install_vllm.sh"
nohup bash "$ROOT/install_vllm.sh" > "$ROOT/vllm-install.log" 2>&1 &
echo "vLLM install running in background, log: $ROOT/vllm-install.log"

echo "== bootstrap done $(date -u +%FT%TZ)"
