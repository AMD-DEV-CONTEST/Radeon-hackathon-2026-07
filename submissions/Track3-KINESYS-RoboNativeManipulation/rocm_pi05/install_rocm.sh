#!/usr/bin/env bash
#
# openpi 一键安装 —— AMD / ROCm 路线（conda 备选；已在 gfx1100 / RX 7900 / ROCm 7.2.1 上验证）。
# 主推路线是 README 的 .venv + apt（无需 conda）；本脚本是功能等价的 conda 备选，install.sh 指向它。
#
# ROCm 路线要点（详见 docs/amd_rocm_jax.md）：
#   - JAX 用 AMD ROCm 0.6.0 (rocm7.0.2) wheel（repo.radeon.com，非 PyPI）。0.6.0 是满足 orbax>=0.5.0
#     且离 fork 生态最近的选择。
#   - ml-dtypes 必须 0.5.4：jaxlib 0.6.0 运行时要 float4_e2m1fn，0.4.1 没有会崩 `import jax`。
#   - torch 走 CPU 构建：避开 jax-rocm7 与 torch-rocm6.4 双 ROCm 运行时符号冲突；训练 GPU 算力是
#     JAX，torch 只做数据管线，CPU 足够。
#   - openpi 用 --no-deps 装：绕开 pyproject 上游遗留的 jax[cuda12]==0.5.3 钉版，保留本脚本装的 AMD jax 0.6.0。
#   - 末尾写 conda activate.d 的 ROCm LD_LIBRARY_PATH，让 JAX 能 dlopen /opt/rocm/lib。
# 共有的依赖坑（本脚本同样处理）：lerobot 的 hub>=1.0 元数据冲突 → --no-deps 装；
#   ffmpeg 8 与 torchcodec 0.5 不兼容 → pin ffmpeg=7；torchcodec CPU 构建。
#
# 用法：
#   bash install_rocm.sh           # 默认环境名 openpi
#   OPENPI_ENV=pi05 bash install_rocm.sh
#
# 前置：主机已装 ROCm（/opt/rocm），且 rocminfo 能识别 gfx1100。
#
# 如需走代理，自行 export（示例）：
#   export http_proxy=http://<proxy-host>:<port>
#   export https_proxy=http://<proxy-host>:<port>
set -euo pipefail

ENV_NAME="${OPENPI_ENV:-openpi}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROCM_REL_URL="https://repo.radeon.com/rocm/manylinux/rocm-rel-7.0.2"
CPU_INDEX="https://download.pytorch.org/whl/cpu"

# shellcheck disable=SC1091
source ~/miniconda3/etc/profile.d/conda.sh

echo ">>> [1/9] 创建 conda 环境 $ENV_NAME (python 3.12)"
conda create -n "$ENV_NAME" python=3.12 -y
conda activate "$ENV_NAME"

echo ">>> [2/9] 安装 ffmpeg 7（torchcodec 0.5 兼容；切勿装默认的 8）"
conda install -c conda-forge "ffmpeg=7.*" -y

cd "$REPO_DIR"

echo ">>> [3/9] 安装 AMD ROCm JAX 0.6.0 (rocm7.0.2) + jaxlib + scipy/numpy"
pip install \
  "$ROCM_REL_URL/jax_rocm7_pjrt-0.6.0-py3-none-manylinux_2_28_x86_64.whl" \
  "$ROCM_REL_URL/jax_rocm7_plugin-0.6.0-cp312-cp312-manylinux_2_28_x86_64.whl" \
  "jax==0.6.0" "jaxlib==0.6.0" "scipy>=1.11.1" "numpy>=1.26,<2.3.0"

echo ">>> [4/9] 安装 ml-dtypes==0.5.4（jaxlib 0.6.0 运行时需要 float4_e2m1fn；--no-deps 防被拖回）"
pip install --no-deps "ml-dtypes==0.5.4"

echo ">>> [5/9] 安装 CPU 版 torch / torchvision（避开双 ROCm 运行时冲突）"
pip install --index-url "$CPU_INDEX" "torch==2.7.1" "torchvision==0.22.1"

echo ">>> [6/9] 安装 openpi 生态依赖（剥掉 AMD jax/torch/ml-dtypes/lerobot 那几行，由前几步与第 8 步处理）"
grep -v -E '^\s*(jax\[|jax==|jaxlib|ml-dtypes|torch==|torchvision|lerobot\[)|^https://repo.radeon.com' requirements_rocm.txt > /tmp/req_rocm.txt
pip install -r /tmp/req_rocm.txt

echo ">>> [7/9] 安装 lerobot 的真实运行依赖（CPU，不挂 cu128 index）+ torchcodec CPU 构建"
pip install \
  "av==15.1.0" \
  "datasets==4.8.5" \
  "pyarrow==25.0.0" \
  "pandas==2.3.3" \
  "draccus==0.10.0" \
  "gymnasium==1.3.0" \
  "jsonlines==4.0.0" \
  "opencv-python==4.11.0.86" \
  "opencv-python-headless==4.11.0.86"
pip install --index-url https://pypi.org/simple "torchcodec==0.5"

echo ">>> [8/9] 安装 lerobot(--no-deps 绕 hub>=1.0 冲突) + openpi editable(--no-deps 绕 pyproject 的 jax[cuda12] 钉版)"
pip install --no-deps "lerobot==0.6.0"
pip install -e . --no-deps

echo ">>> [9/9] 打 PyTorch 后端的 transformers 补丁 + 写 conda activate.d 的 ROCm 环境变量"
cp -r src/openpi/models_pytorch/transformers_replace/* \
  "$(python -c 'import transformers,os;print(os.path.dirname(transformers.__file__))')"

ACT_DIR="$CONDA_PREFIX/etc/conda/activate.d"
DEACT_DIR="$CONDA_PREFIX/etc/conda/deactivate.d"
mkdir -p "$ACT_DIR" "$DEACT_DIR"
cat > "$ACT_DIR/zz-rocm.sh" <<'EOF'
# 由 install_rocm.sh 写入：让 JAX 能 dlopen /opt/rocm/lib 下的 HIP/MIOpen 库
export ROCM_PATH="${ROCM_PATH:-/opt/rocm}"
export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH}"
EOF
cat > "$DEACT_DIR/zz-rocm.sh" <<'EOF'
# 由 install_rocm.sh 写入
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH#/opt/rocm/lib:}"
[ -z "$LD_LIBRARY_PATH" ] && unset LD_LIBRARY_PATH
unset ROCM_PATH
EOF

echo
echo "完成。后续使用："
echo "  conda activate $ENV_NAME      # 自动设好 ROCM_PATH / LD_LIBRARY_PATH"
echo "  验证 JAX 看到 AMD GPU:  python -c \"import jax; print(jax.devices())\"   # 期望 [RocmDevice(id=0)]"
echo "  验证训练入口可加载:    python train_jax.py --help   # 期望 EXIT=0"
echo "  base checkpoint 获取与训练/推理用法、显存与 GPU 占用性能指标见 docs/amd_rocm_jax.md"
