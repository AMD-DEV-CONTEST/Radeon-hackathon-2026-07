#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — 构建脚本
# 安装项目 Python 依赖，可选编译 ROCm 优化内核
# ============================================================

set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 加载环境配置 ----------
if [[ -f .env ]]; then
    source .env
    info "已加载 .env 配置文件"
fi

# ---------- 确定 Python ----------
PY_BIN="${PYTHON_BIN:-python3}"
if [[ -f /opt/venv/bin/python3 ]]; then
    PY_BIN="/opt/venv/bin/python3"
elif [[ -f .venv/bin/python3 ]]; then
    PY_BIN=".venv/bin/python3"
fi

# ---------- 检查 GPU -----------
GPU_TYPE="${GPU_TYPE:-}"
if [[ -z "$GPU_TYPE" ]]; then
    if command -v rocm-smi &>/dev/null; then GPU_TYPE="amd"
    elif command -v nvidia-smi &>/dev/null; then GPU_TYPE="nvidia"
    else GPU_TYPE="cpu"; fi
fi

info "GPU 类型: $GPU_TYPE"
info "Python: $($PY_BIN --version 2>&1)"
info "项目目录: $(pwd)"

BUILD_MODE="${1:-all}"  # all | deps | compile

# ============================================================
#  1. 安装 Python 依赖
# ============================================================
install_deps() {
    echo ""
    echo "==========  安装 Python 依赖  =========="

    # 升级 pip
    $PY_BIN -m pip install --upgrade pip --quiet --no-cache-dir

    # 根据 GPU 类型选择 torch 源
    TORCH_INDEX=""
    if [[ "$GPU_TYPE" == "amd" ]]; then
        ROCM_VER="${ROCM_VERSION:-}"
        if [[ -z "$ROCM_VER" ]]; then
            if [[ -f /opt/rocm/.info/version ]]; then
                ROCM_VER=$(cat /opt/rocm/.info/version)
            fi
        fi
        case "$ROCM_VER" in
            7.2*|7.1*|7.0*) TORCH_INDEX="https://download.pytorch.org/whl/rocm7.2" ;;
            6.*) TORCH_INDEX="https://download.pytorch.org/whl/rocm6.2" ;;
        esac
        if [[ -n "$TORCH_INDEX" ]]; then
            info "使用 ROCm PyTorch 源: $TORCH_INDEX"
            MAX_JOBS=2 $PY_BIN -m pip install torch torchvision --index-url "$TORCH_INDEX" --no-cache-dir 2>&1 | tail -3 || true
        fi
    elif [[ "$GPU_TYPE" == "nvidia" ]]; then
        TORCH_INDEX="https://download.pytorch.org/whl/cu124"
        info "使用 CUDA PyTorch 源: $TORCH_INDEX"
        MAX_JOBS=2 $PY_BIN -m pip install torch torchvision --index-url "$TORCH_INDEX" --no-cache-dir 2>&1 | tail -3 || true
    fi

    # 安装项目依赖
    info "安装项目依赖..."
    $PY_BIN -m pip install -r requirements.txt --no-cache-dir 2>&1 | tail -5

    ok "依赖安装完成！"
}

# ============================================================
#  2. 编译 ROCm 优化内核（可选）
# ============================================================
compile_rocm_kernels() {
    echo ""
    echo "==========  编译 ROCm 优化内核  =========="

    if [[ "$GPU_TYPE" != "amd" ]]; then
        info "非 AMD GPU，跳过内核编译"
        return
    fi

    # 编译 Triton ROCm 内核（FlashAttention 等）
    info "安装 Triton (ROCm)..."
    MAX_JOBS=2 $PY_BIN -m pip install --upgrade triton --no-cache-dir 2>&1 | tail -3 || warn "Triton 安装失败"

    # 可选: 编译 xformers ROCm 版
    if [[ "$BUILD_MODE" == "all" ]] || [[ "$BUILD_MODE" == "compile" ]]; then
        info "尝试编译 xformers (ROCm)..."
        MAX_JOBS=2 $PY_BIN -m pip install xformers --index-url "$TORCH_INDEX" --no-cache-dir 2>&1 | tail -3 || \
            warn "xformers 编译安装失败（不影响核心功能）"
    fi

    ok "ROCm 优化内核就绪"
}

# ============================================================
#  3. 编译前端资源
# ============================================================
build_assets() {
    echo ""
    echo "==========  构建前端资源  =========="
    # Gradio 应用不需要额外构建，直接运行
    ok "Gradio 应用无需构建步骤"
}

# ============================================================
#  Main
# ============================================================
main() {
    info "构建模式: $BUILD_MODE"

    case "$BUILD_MODE" in
        all)
            install_deps
            compile_rocm_kernels
            build_assets
            ;;
        deps)
            install_deps
            ;;
        compile)
            compile_rocm_kernels
            ;;
        *)
            err "未知模式: $BUILD_MODE (可选: all, deps, compile)"
            exit 1
            ;;
    esac

    echo ""
    ok "构建完成！执行以下命令启动:"
    echo ""
    echo "  cd $(pwd)"
    echo "  $PY_BIN app.py"
    echo ""
}

main
