#!/bin/bash
#
# Radeon-Assistant — ROCm (AMD) 安装脚本
#
# ROCm-ONLY — CUDA 已拉黑。本机为 AMD Radeon（ROCm）环境，无任何 NVIDIA GPU / CUDA 运行时。
# 切勿执行 `pip install -r requirements.txt` 来装深度学习栈，也切勿使用 wheels.vllm.ai 或
# download.pytorch.org 的 CUDA 构建——它们会拉入 libcuda.so.1，导致 vLLM/torch 在碰设备时崩溃。
#
# 本脚本按「官方 AMD Radeon vLLM ROCm 文档」在 AMD Radeon Pro W7900D (gfx1100) 上验证可用：
# - Python 3.14 venv (/opt/venv314)
# - uv + AMD ROCm 7.14 源（repo.amd.com / rocm.frameworks.amd.com）
# - glibc 2.35 (Ubuntu 22.04) 兼容 shim
#
# 如需离线/旧方案（6.2 时代），请勿使用：官方已不再托管对应 wheel。

set -euo pipefail

VENV="${VENV:-/opt/venv314}"
PYTHON_VER="${PYTHON_VER:-3.14}"

echo "=== Radeon-Assistant vLLM (ROCm 7.14) 安装脚本 ==="
echo "目标 venv: $VENV"
echo ""

# ---- 0. 创建 Python 3.14 虚拟环境 ----
echo "0. 准备 Python $PYTHON_VER venv @ $VENV ..."
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv python install "$PYTHON_VER" || true
    uv venv --python "$PYTHON_VER" "$VENV"
  else
    python"${PYTHON_VER}" -m venv "$VENV"
  fi
fi
# 优先用 uv pip（快且能正确解析 AMD 源）
if command -v uv >/dev/null 2>&1; then
  PIP_CMD=(uv pip install --python "$VENV")
else
  PIP_CMD=("$VENV/bin/pip" install)
fi

# ---- 1. 安装 torch / torchvision / torchaudio (ROCm 7.14, gfx1100) ----
echo ""
echo "1. 安装 torch / torchvision / torchaudio (AMD ROCm 7.14) ..."
"${PIP_CMD[@]}" --index-url https://repo.amd.com/rocm/whl-multi-arch/ \
  "torch[device-gfx1100]==2.11.0+rocm7.14.0" \
  "torchvision[device-gfx1100]==0.26.0+rocm7.14.0" \
  "torchaudio==2.11.0+rocm7.14.0"

# ---- 2. 安装 flash-attn (ROCm 构建) ----
echo ""
echo "2. 安装 flash-attn (2.8.3, ROCm RDNA) ..."
"${PIP_CMD[@]}" https://rocm.frameworks.amd.com/whl-multi-arch/vllm-rdna/flash-attn/flash_attn-2.8.3-py3-none-any.whl

# ---- 3. 安装 vLLM (ROCm 7.14 wheel, Python 3.14) ----
echo ""
echo "3. 安装 vLLM (0.23.1.dev1+rocm7.14.0) ..."
"${PIP_CMD[@]}" https://rocm.frameworks.amd.com/whl-multi-arch/vllm-rdna/vllm/vllm-0.23.1.dev1%2Brocm7.14.0.g9ddef7117.d20260715-cp314-cp314-linux_x86_64.whl

# ---- 4. 安装其余纯 Python / CPU 侧依赖（不含 DL 栈）----
echo ""
echo "4. 安装 CPU 侧依赖 (requirements.txt 中除 DL 栈外的部分) ..."
# 过滤掉 requirements.txt 中可能残留的 torch/vllm/flash-attn/transformers 行，避免误拉 CUDA
grep -vE '^\s*(torch|torchvision|torchaudio|vllm|flash-attn|xformers|transformers)\b' requirements.txt \
  > /tmp/ra_requirements_cpu.txt || true
"${PIP_CMD[@]}" -r /tmp/ra_requirements_cpu.txt

# ---- 5. glibc 2.35 (Ubuntu 22.04) 兼容 shim ----
# 官方 wheel 构建于 glibc 2.38，引用 __isoc23_strtol / __isoc23_strtoull@GLIBC_2.38，
# 在 glibc 2.35 上会报 `version GLIBC_2.38 not found` 导致 import vllm._C_stable_libtorch 失败。
echo ""
echo "5. 检查 / 构建 glibc 2.35 兼容 shim ..."
SHIM="$VENV/lib/libisoc23_shim.so"
if [ ! -f "$SHIM" ]; then
  echo " 构建 $SHIM ..."
  cat > /tmp/isoc23_shim.c <<'EOF'
#define _GNU_SOURCE
#include <stdlib.h>
long __isoc23_strtol(const char *n, char **e, int b){return strtol(n,e,b);}
long long __isoc23_strtoll(const char *n, char **e, int b){return strtoll(n,e,b);}
unsigned long __isoc23_strtoul(const char *n, char **e, int b){return strtoul(n,e,b);}
unsigned long long __isoc23_strtoull(const char *n, char **e, int b){return strtoull(n,e,b);}
EOF
  echo 'GLIBC_2.35 { __isoc23_strtol; __isoc23_strtoll; __isoc23_strtoul; __isoc23_strtoull; };' > /tmp/isoc23_vers.map
  gcc -shared -fPIC -O2 -Wl,--version-script=/tmp/isoc23_vers.map -o "$SHIM" /tmp/isoc23_shim.c
fi
echo " shim: $SHIM"

# ---- 6. 校验安装 ----
echo ""
echo "6. 校验安装 (ROCm 构建, 无 CUDA 污染) ..."
LD_PRELOAD="$SHIM" \
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
PYTHONPATH="$VENV/lib/python3.14/site-packages/_rocm_sdk_core/share/amd_smi" \
FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE \
"$VENV/bin/python" -c "
import os
os.environ['HSA_OVERRIDE_GFX_VERSION'] = '11.0.0'
import torch, vllm, flash_attn
print('torch :', torch.__version__)
print('vllm :', vllm.__version__)
print('GPU 可用 (HIP 后端):', torch.cuda.is_available())
assert 'rocm' in torch.__version__, 'torch 不是 ROCm 构建!'
print('ROCm 构建校验通过')
"

echo ""
echo "=== 安装完成 ==="
echo "运行时 ROCm 环境变量已汇总到仓库自带脚本 setenv-rocm.sh，启动任何命令前 source 即可："
echo ""
echo "  source setenv-rocm.sh            # 加载 ROCm 环境 + 激活 venv + glibc shim"
echo "  python scripts/download_model.py --model qwen2.5-14b"
echo "  python app.py --mode cli         # 或 --mode web"
echo "  python scripts/benchmark.py --model qwen2.5-14b"
echo "  python scripts/serve.py --model qwen2.5-14b"
echo ""
echo "(手动设置等价于 setenv-rocm.sh 内的 export；VENV 可用环境变量覆盖)"
