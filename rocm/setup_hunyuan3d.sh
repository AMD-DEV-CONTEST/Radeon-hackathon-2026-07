#!/usr/bin/env bash
# 单独安装 Hunyuan3D-2，用于本地图生 3D 全彩模型。
# 纹理模块的 custom rasterizer 在 ROCm 上可能编译失败，此时脚本会退回到仅形状生成。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HUNYUAN_DIR="$PROJECT_ROOT/external/Hunyuan3D-2"

echo "============================================"
echo "安装 Hunyuan3D-2 用于图生 3D 全彩模型"
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "HUNYUAN_DIR: $HUNYUAN_DIR"
echo "============================================"

cd "$PROJECT_ROOT/services/api"
source .venv/bin/activate

# 1. 确保基础编译工具
sudo apt-get update
sudo apt-get install -y build-essential git || true

# 2. 克隆 Hunyuan3D-2 仓库（处理证书缺失环境）
echo "[1/3] 克隆 Hunyuan3D-2 仓库..."
if [ ! -d "$HUNYUAN_DIR/.git" ]; then
    mkdir -p "$HUNYUAN_DIR"
    git -c http.sslVerify=false clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git "$HUNYUAN_DIR"
else
    cd "$HUNYUAN_DIR"
    git -c http.sslVerify=false pull --ff-only
fi

cd "$HUNYUAN_DIR"

# 3. 安装 Python 依赖
echo "[2/3] 安装 Hunyuan3D-2 Python 依赖..."
pip install -r requirements.txt \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org

# 4. 安装 hy3dgen 包（允许形状-only 回退）
echo "[3/3] 安装 hy3dgen 包..."
if pip install -e . --no-build-isolation \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org; then
    echo "Hunyuan3D-2 完整安装成功（包含纹理模块）"
else
    echo "警告：Hunyuan3D-2 完整安装失败，尝试仅安装形状生成模块..."
    pip install -e . --no-build-isolation --no-deps \
        --trusted-host pypi.org --trusted-host files.pythonhosted.org
    echo "Hunyuan3D-2 形状-only 安装完成。纹理模块不可用。"
fi

cd "$PROJECT_ROOT/services/api"

# 5. 验证
echo "验证 Hunyuan3D-2 导入..."
python - <<'PY'
try:
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
    print("OK: hy3dgen.shapegen 可导入")
except Exception as exc:
    print(f"FAIL: hy3dgen.shapegen 导入失败: {exc}")

try:
    from hy3dgen.texgen import Hunyuan3DPaintPipeline
    print("OK: hy3dgen.texgen 可导入（纹理可用）")
except Exception as exc:
    print(f"WARN: hy3dgen.texgen 导入失败: {exc}")
PY

echo ""
echo "Hunyuan3D-2 安装完成。启动后端时设置 USE_ROCM=true 和 USE_HUNYUAN3D=true 即可启用。"
