#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — 启动脚本
# 自动激活虚拟环境、检查 GPU、启动 Web UI
# ============================================================

set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 加载环境 ----------
if [[ -f .env ]]; then
    source .env
fi

# ---------- 参数 ----------
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-7860}"
SHARE="${SHARE:-false}"
DEBUG="${DEBUG:-false}"
MODE="${1:-web}"   # web | headless | api

# ---------- 确定 Python ----------
PY_BIN="${PYTHON_BIN:-python3}"
if [[ -f /opt/venv/bin/python3 ]]; then
    PY_BIN="/opt/venv/bin/python3"
    # 激活虚拟环境
    source /opt/venv/bin/activate
    info "已激活虚拟环境: /opt/venv"
elif [[ -f .venv/bin/python3 ]]; then
    PY_BIN=".venv/bin/python3"
    source .venv/bin/activate
    info "已激活虚拟环境: .venv"
fi

# ---------- 检测 GPU ----------
echo "==========  AMD AI Studio 启动  =========="
info "时间: $(date '+%Y-%m-%d %H:%M:%S')"
info "Python: $($PY_BIN --version 2>&1)"
info "项目: $(pwd)"

if $PY_BIN -c "import torch; print(torch.cuda.is_available())" 2>/dev/null; then
    ROCM_VER=$($PY_BIN -c "import torch; print(torch.version.rocm)" 2>/dev/null || echo "未知")
    GPU_NAME=$($PY_BIN -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null || echo "未知")
    GPU_COUNT=$($PY_BIN -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo 0)
    ok "GPU: $GPU_NAME (${GPU_COUNT}块, ROCm ${ROCM_VER})"
else
    warn "GPU 不可用，将使用 CPU 模式（速度较慢）"
fi

# ---------- 启动 ----------
start_web() {
    echo ""
    info "启动 Web UI..."
    echo "  地址: http://$HOST:$PORT"
    echo "  共享: $SHARE"
    echo "=========================================="
    echo ""

    exec $PY_BIN app.py \
        --server-name "$HOST" \
        --server-port "$PORT" \
        $([[ "$SHARE" == "true" ]] && echo "--share") \
        $([[ "$DEBUG" == "true" ]] && echo "--debug")
}

start_headless() {
    echo ""
    info "启动命令行模式..."
    echo ""

    exec $PY_BIN -c "
from modules.txt2img import generate_txt2img
from modules.rocm_utils import format_gpu_info

print(format_gpu_info())
print()

import sys
prompt = sys.argv[1] if len(sys.argv) > 1 else input('请输入提示词: ')
images = generate_txt2img(prompt=prompt, num_images=1)
img = images[0]
path = f'outputs/images/headless_$(date +%Y%m%d_%H%M%S).png'
img.save(path)
print(f'图像已保存: {path}')
" "$@"
}

case "$MODE" in
    web)
        start_web
        ;;
    headless)
        shift; start_headless
        ;;
    api)
        info "API 模式: 启动 Gradio API..."
        exec $PY_BIN app.py --server-name "$HOST" --server-port "$PORT"
        ;;
    *)
        err "未知模式: $MODE (可选: web, headless, api)"
        exit 1
        ;;
esac
