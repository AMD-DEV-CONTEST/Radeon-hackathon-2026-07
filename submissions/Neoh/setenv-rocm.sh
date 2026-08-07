#!/bin/bash
# ============================================================================
# Radeon-Assistant — ROCm 运行时环境（gfx1100 + glibc 2.35 兼容）
#
# 本文件就是「测试 / 评测环境跑起来必须用到的」ROCm 环境集合，
# 不依赖任何开发期专用说明。在启动任何命令之前 source 本文件即可，
# 不必在每条命令前手动加 env 前缀：
#
#   source setenv-rocm.sh
#   python app.py --mode cli
#   python app.py --mode web --port 7860
#   python scripts/benchmark.py --model qwen2.5-14b
#   python scripts/serve.py --model qwen2.5-14b
#   streamlit run ui/web_app.py --server.port 7860
#
# 要点：
# - LD_PRELOAD 指向 install_rocm.sh 生成的 glibc 2.35 兼容 shim，必须在 shell 启动前注入，
#   无法在 Python 代码内设置，故只能放在这里（或命令前缀）。
# - PYTHONPATH 指向 AMD ROCm SDK 的 amd_smi 模块路径（vLLM/torch 运行时依赖）。
# - 默认使用 /opt/venv314；可用 `VENV=/your/venv source setenv-rocm.sh` 覆盖。
# - ROCm-ONLY：本环境无 NVIDIA GPU / CUDA，深度学习栈必须来自 AMD ROCm 源。
# ============================================================================
set -e

VENV="${VENV:-/opt/venv314}"
SHIM="$VENV/lib/libisoc23_shim.so"

if [ ! -f "$SHIM" ]; then
  echo "[setenv-rocm] 警告: glibc shim 不存在: $SHIM" >&2
  echo "[setenv-rocm] 请先运行: bash install_rocm.sh" >&2
  echo "[setenv-rocm] 跳过 LD_PRELOAD（vLLM/torch 可能因 glibc 2.35 缺少符号而报错）" >&2
else
  export LD_PRELOAD="$SHIM"
fi
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export PYTORCH_ROCM_ARCH=gfx1100
export FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE
export PYTHONPATH="$VENV/lib/python3.14/site-packages/_rocm_sdk_core/share/amd_smi"

# 自动激活 venv（若尚未激活）
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "$VENV/bin/activate" ]; then
  source "$VENV/bin/activate"
fi

echo "[setenv-rocm] ROCm 运行时环境已加载 (venv=$VENV, gfx1100)"
