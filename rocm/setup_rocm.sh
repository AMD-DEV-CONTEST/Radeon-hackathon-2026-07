#!/usr/bin/env bash
# ROCm 环境初始化脚本（Ubuntu/Debian 系）
# 用法：在项目根目录执行  ./rocm/setup_rocm.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================"
echo "3DGenerateFlow ROCm 环境初始化"
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "============================================"

# 1. 基础检查
if ! command -v python3 &>/dev/null; then
    echo "[1/6] 安装 python3 与 python3-venv..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip python3-venv python3-dev git wget curl
else
    echo "[1/6] python3 已安装"
fi

# 确保 venv 模块可用（Ubuntu 24.04 需要 python3.12-venv）
if ! python3 -m venv --help &>/dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3-venv
fi

# 2. 检查 ROCm 是否已安装，并根据 Ubuntu 版本选择 ROCm 版本
ROCM_VERSION="6.0"
UBUNTU_CODENAME="jammy"
PYTORCH_INDEX="https://download.pytorch.org/whl/rocm6.0"
PYTORCH_TORCH="torch==2.3.1+rocm6.0"
PYTORCH_VISION="torchvision==0.18.1+rocm6.0"
PYTORCH_AUDIO="torchaudio==2.3.1+rocm6.0"

if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    echo "OS: $NAME $VERSION_ID ($VERSION_CODENAME)"
    case "${VERSION_CODENAME:-}" in
        noble)
            ROCM_VERSION="6.1.5"
            UBUNTU_CODENAME="noble"
            PYTORCH_INDEX="https://download.pytorch.org/whl/rocm6.1"
            PYTORCH_TORCH="torch==2.5.1+rocm6.1"
            PYTORCH_VISION="torchvision==0.20.1+rocm6.1"
            PYTORCH_AUDIO="torchaudio==2.5.1+rocm6.1"
            ;;
        jammy)
            ROCM_VERSION="6.0"
            UBUNTU_CODENAME="jammy"
            ;;
        *)
            echo "未识别的 Ubuntu 版本 ${VERSION_CODENAME}，使用默认 jammy + ROCm 6.0 配置"
            ;;
    esac
fi

if command -v rocminfo &>/dev/null && command -v hipcc &>/dev/null; then
    echo "[2/6] ROCm 已检测到，跳过系统 ROCm 安装："
    rocminfo | grep -E "Marketing Name:|Device Type:" | head -n 5 || true
else
    echo "[2/6] 未检测到 ROCm，尝试安装 ROCm ${ROCM_VERSION} 基础包..."

    sudo mkdir -p --mode=0755 /usr/share/keyrings
    wget --no-check-certificate -qO - https://repo.radeon.com/rocm/rocm.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/rocm.gpg

    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/${ROCM_VERSION} ${UBUNTU_CODENAME} main" | sudo tee /etc/apt/sources.list.d/rocm.list
    sudo apt-get update --allow-insecure-repositories || sudo apt-get update
    sudo apt-get install -y --allow-unauthenticated rocm-dev rocm-hip-runtime rocm-utils rocminfo || \
        sudo apt-get install -y rocm-dev rocm-hip-runtime rocm-utils rocminfo

    # 添加环境变量（当前 shell）
    export PATH="/opt/rocm/bin:$PATH"
    export LD_LIBRARY_PATH="/opt/rocm/lib:$LD_LIBRARY_PATH"

    echo "export PATH=/opt/rocm/bin:\$PATH" >> ~/.bashrc
    echo "export LD_LIBRARY_PATH=/opt/rocm/lib:\$LD_LIBRARY_PATH" >> ~/.bashrc
fi

# 3. 创建 Python 虚拟环境并安装 ROCm 版 PyTorch
echo "[3/6] 创建 Python 虚拟环境 ..."
cd "$PROJECT_ROOT/services/api"
python3 -m venv .venv
source .venv/bin/activate

# 升级 pip
pip install --upgrade pip setuptools wheel --trusted-host pypi.org --trusted-host files.pythonhosted.org

# 安装 ROCm 版 PyTorch（根据 Ubuntu 版本自动选择）
echo "[3/6] 安装 ROCm 版 PyTorch (${PYTORCH_TORCH}) ..."
pip install ${PYTORCH_TORCH} ${PYTORCH_VISION} ${PYTORCH_AUDIO} \
    --index-url ${PYTORCH_INDEX} \
    --trusted-host download.pytorch.org --trusted-host pypi.org --trusted-host files.pythonhosted.org

# 验证
echo "[3/6] 验证 PyTorch ROCm ..."
python - <<'PY'
import torch
print(f"PyTorch version: {torch.__version__}")
print(f"HIP version: {torch.version.hip}")
print(f"CUDA available (for ROCm this is also True): {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU count: {torch.cuda.device_count()}")
    print(f"GPU name: {torch.cuda.get_device_name(0)}")
    print(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1024**2:.0f} MB")
PY

# 4. 安装项目依赖（不含 torch，已单独安装）
echo "[4/6] 安装项目依赖 ..."
# certifi 用于在系统 CA 缺失时下载 HuggingFace 模型
pip install certifi --trusted-host pypi.org --trusted-host files.pythonhosted.org
pip install -r requirements-rocm.txt \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org

# 5. 预下载模型（可选，建议比赛前执行）
echo "[5/6] 预下载 HuggingFace 模型到本地缓存 ..."
# 在系统证书缺失的环境下，使用 certifi 的 CA 包或临时关闭 HTTPS 验证
export PYTHONHTTPSVERIFY=0
export REQUESTS_CA_BUNDLE=$(python -c "import certifi; print(certifi.where())" 2>/dev/null || true)
python - <<'PY'
import os
from diffusers import StableDiffusionImg2ImgPipeline
from transformers import pipeline

cache_dir = os.path.abspath("./models/hf_cache")
os.makedirs(cache_dir, exist_ok=True)

print("Downloading Stable Diffusion v1.5 ...")
StableDiffusionImg2ImgPipeline.from_pretrained(
    "runwayml/stable-diffusion-v1-5",
    cache_dir=cache_dir,
    torch_dtype="auto",
    safety_checker=None,
)

print("Downloading Depth Anything v2 small ...")
pipeline(
    "depth-estimation",
    model="depth-anything/Depth-Anything-V2-Small-hf",
    cache_dir=cache_dir,
)

print("Model cache dir:", cache_dir)
PY
unset PYTHONHTTPSVERIFY
unset REQUESTS_CA_BUNDLE

# 6. 完成提示
echo "[6/6] 环境初始化完成。"
echo ""
echo "启动开发服务器："
echo "  cd services/api"
echo "  source .venv/bin/activate"
echo "  CELERY_TASK_ALWAYS_EAGER=true CELERY_RESULT_BACKEND=cache+memory:// CELERY_TASK_EAGER_PROPAGATES=true PYTHONPATH=../.. uvicorn main:app --reload"
echo ""
echo "启动前端："
echo "  cd apps/web"
echo "  npm install"
echo "  npm run dev"
