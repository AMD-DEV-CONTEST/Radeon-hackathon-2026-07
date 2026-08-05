#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — 一键检测 & 依赖安装脚本
# 检测系统硬件、Python/ROCm环境，自动安装缺失依赖
# ============================================================

set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }
SEP="----------------------------------------"

# ---------- 项目根目录 ----------
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${VENV_DIR:-/opt/venv}"

# ---------- 包管理器 ----------
detect_pkg_manager() {
    if command -v apt &>/dev/null; then PM="apt"; PM_INSTALL="apt install -y"; PM_UPDATE="apt update"
    elif command -v yum &>/dev/null; then PM="yum"; PM_INSTALL="yum install -y"; PM_UPDATE="yum makecache"
    elif command -v dnf &>/dev/null; then PM="dnf"; PM_INSTALL="dnf install -y"; PM_UPDATE="dnf makecache"
    elif command -v pacman &>/dev/null; then PM="pacman"; PM_INSTALL="pacman -S --noconfirm"; PM_UPDATE="pacman -Sy"
    else err "不支持的包管理器"; exit 1; fi
    ok "包管理器: $PM"
}

SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"

# ============================================================
#  1. 硬件检测
# ============================================================
check_hardware() {
    echo -e "\n==========  硬件信息  =========="
    echo "$SEP"
    if [[ -f /proc/cpuinfo ]]; then
        CPU_MODEL=$(grep -m1 "model name" /proc/cpuinfo | cut -d: -f2 | sed 's/^ //')
        CPU_CORES=$(grep -c ^processor /proc/cpuinfo)
        info "CPU: ${CPU_MODEL:-N/A} (${CPU_CORES:-N/A} 核心)"
    fi
    info "架构: $(uname -m)"

    echo "$SEP"
    if command -v free &>/dev/null; then
        MEM_TOTAL=$(free -h | awk '/^Mem:/{print $2}')
        MEM_AVAIL=$(free -h | awk '/^Mem:/{print $7}')
        info "内存: 总量 $MEM_TOTAL, 可用 $MEM_AVAIL"
    fi

    echo "$SEP"
    GPU_TYPE="none"
    if command -v rocm-smi &>/dev/null; then
        GPU_TYPE="amd"
        info "AMD GPU (ROCm):"
        rocm-smi --showproductname 2>/dev/null | grep -E "^GPU" | head -8 | sed 's/^/  /'
        rocm-smi --showmeminfo vram 2>/dev/null | grep "VRAM Total" | head -4
    elif command -v nvidia-smi &>/dev/null; then
        GPU_TYPE="nvidia"
        info "NVIDIA GPU:"
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -4 | sed 's/^/  /'
    elif command -v lspci &>/dev/null; then
        GPU_INFO=$(lspci | grep -iE 'vga|3d|display' | head -5)
        if echo "$GPU_INFO" | grep -qi amd; then GPU_TYPE="amd"; fi
        if echo "$GPU_INFO" | grep -qi nvidia; then GPU_TYPE="nvidia"; fi
        [[ -n "$GPU_INFO" ]] && info "GPU 设备:\n$GPU_INFO" | sed 's/^/  /' || warn "未检测到 GPU"
    fi

    echo "$SEP"
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release; info "OS: $PRETTY_NAME"
    fi
    info "内核: $(uname -r)"
}

# ============================================================
#  2. Python 环境检测
# ============================================================
check_python_env() {
    echo -e "\n==========  Python 环境检测  =========="

    # 检测系统 Python
    if command -v python3 &>/dev/null; then
        PY_SYS_VER=$(python3 --version 2>&1)
        ok "系统 Python: $PY_SYS_VER"
    else
        err "Python3 未安装，请先安装: $SUDO $PM_INSTALL python3 python3-pip python3-venv"
        return 1
    fi

    # 检测虚拟环境
    VENV_PY=""
    if [[ -f "$VENV_DIR/bin/python3" ]]; then
        VENV_PY="$VENV_DIR/bin/python3"
        ok "虚拟环境: $VENV_DIR ($($VENV_PY --version 2>&1))"
    else
        warn "虚拟环境不存在: $VENV_DIR"
        read -rp "是否创建虚拟环境? [Y/n]: " cr_venv
        cr_venv=${cr_venv:-Y}
        if [[ "$cr_venv" =~ ^[Yy]$ ]]; then
            python3 -m venv "$VENV_DIR" && ok "虚拟环境已创建: $VENV_DIR" || err "创建失败"
            VENV_PY="$VENV_DIR/bin/python3"
        else
            VENV_PY="python3"
            warn "将使用系统 Python (不推荐)"
        fi
    fi

    PY_BIN="${VENV_PY:-python3}"
}

# ============================================================
#  3. ROCm / CUDA 检测
# ============================================================
check_rocm() {
    echo -e "\n==========  ROCm / CUDA 检测  =========="

    if [[ -d /opt/rocm ]]; then
        ROCM_VER=$(cat /opt/rocm/.info/version 2>/dev/null || echo "未知")
        ok "ROCm 已安装: $ROCM_VER ($(readlink -f /opt/rocm))"
    else
        warn "ROCm 未安装在 /opt/rocm"
    fi

    if [[ -n "$PY_BIN" ]]; then
        echo "$SEP"
        info "检测 PyTorch & ROCm 绑定..."
        $PY_BIN -c "
import sys
try:
    import torch
    print(f'  PyTorch : {torch.__version__}')
    print(f'  CUDA可用: {torch.cuda.is_available()}')
    if torch.cuda.is_available():
        print(f'  ROCm    : {torch.version.rocm}')
        print(f'  GPU数量 : {torch.cuda.device_count()}')
        for i in range(torch.cuda.device_count()):
            print(f'    GPU {i}: {torch.cuda.get_device_name(i)} ({torch.cuda.get_device_properties(i).total_memory / 1024**3:.1f} GB)')
except ImportError:
    print('  PyTorch: 未安装')
except Exception as e:
    print(f'  PyTorch 导入异常: {e}')
" 2>&1
    fi

    # 检测 diffusers
    if [[ -n "$PY_BIN" ]]; then
        echo "$SEP"
        $PY_BIN -c "
try:
    import diffusers; print(f'  Diffusers: {diffusers.__version__}')
except: print('  Diffusers: 未安装')
try:
    import gradio; print(f'  Gradio   : {gradio.__version__}')
except: print('  Gradio   : 未安装')
" 2>&1
    fi
}

# ============================================================
#  4. 检测缺失依赖并安装
# ============================================================
MISSING_PKGS=()

check_dep() {
    local name="$1"; local pkg="$2"; local check_cmd="$3"; local install_cmd="$4"
    if eval "$check_cmd" &>/dev/null; then
        ok "$name: 已安装"
    else
        warn "$name: 未安装"
        MISSING_PKGS+=("$name:$pkg:$install_cmd")
    fi
}

check_deps() {
    echo -e "\n==========  依赖检测  =========="

    check_dep "PyTorch"      "torch"      "$PY_BIN -c 'import torch'"              ""
    check_dep "Diffusers"    "diffusers"  "$PY_BIN -c 'import diffusers'"           ""
    check_dep "Gradio"       "gradio"     "$PY_BIN -c 'import gradio'"              ""
    check_dep "Transformers" "transformers" "$PY_BIN -c 'import transformers'"      ""
    check_dep "Accelerate"   "accelerate" "$PY_BIN -c 'import accelerate'"         ""
    check_dep "OpenCV"       "opencv-python" "$PY_BIN -c 'import cv2'"              ""
    check_dep "Pillow"       "Pillow"     "$PY_BIN -c 'from PIL import Image'"      ""
    check_dep "imageio"      "imageio"    "$PY_BIN -c 'import imageio'"             ""
    check_dep "safetensors"  "safetensors" "$PY_BIN -c 'import safetensors'"        ""

    echo ""
    info "共 ${#MISSING_PKGS[@]} 个依赖缺失"
}

install_deps() {
    echo -e "\n==========  安装依赖  =========="

    if [[ ${#MISSING_PKGS[@]} -eq 0 ]]; then
        ok "所有依赖已安装，无需操作！"
        return
    fi

    # 更新 pip
    info "升级 pip..."
    $PY_BIN -m pip install --upgrade pip --quiet --no-cache-dir 2>/dev/null || true

    # 将缺失包分类安装
    PYTHON_PKGS=()
    for dep in "${MISSING_PKGS[@]}"; do
        pkg_name="${dep#*:}"
        install_cmd="${pkg_name#*:}"
        pkg_name="${pkg_name%%:*}"
        PYTHON_PKGS+=("$pkg_name")
    done

    if [[ ${#PYTHON_PKGS[@]} -gt 0 ]]; then
        info "安装 Python 包: ${PYTHON_PKGS[*]}"
        MAX_JOBS=2 $PY_BIN -m pip install --no-cache-dir "${PYTHON_PKGS[@]}" 2>&1 | tail -3
    fi

    # 验证安装
    echo "$SEP"
    info "验证安装..."
    for dep in "${MISSING_PKGS[@]}"; do
        pkg="${dep#*:}"; pkg="${pkg%%:*}"
        if $PY_BIN -c "import $pkg" 2>/dev/null; then
            ok "$pkg: 安装成功"
        else
            warn "$pkg: 安装可能失败"
        fi
    done
}

# ============================================================
#  5. 系统依赖安装
# ============================================================
install_system_deps() {
    echo -e "\n==========  系统依赖安装  =========="
    local sys_pkgs=()

    if command -v ffmpeg &>/dev/null; then ok "ffmpeg: 已安装"
    else sys_pkgs+=("ffmpeg"); fi

    if command -v git-lfs &>/dev/null; then ok "git-lfs: 已安装"
    else sys_pkgs+=("git-lfs"); fi

    if command -v nocache &>/dev/null; then ok "nocache: 已安装"
    else sys_pkgs+=("nocache"); fi

    if [[ ${#sys_pkgs[@]} -gt 0 ]]; then
        info "安装系统包: ${sys_pkgs[*]}"
        $SUDO $PM_INSTALL "${sys_pkgs[@]}" 2>&1 | tail -3 || true
    else
        ok "系统依赖已全部安装"
    fi
}

# ============================================================
#  6. 最终摘要
# ============================================================
print_summary() {
    echo -e "\n=========================================="
    echo "  AMD AI Studio — 环境检测摘要"
    echo "=========================================="
    echo "  项目目录: $PROJECT_DIR"
    echo "  Python: $($PY_BIN --version 2>&1)"
    echo "  PyTorch: $($PY_BIN -c 'import torch; print(torch.__version__)' 2>/dev/null || echo '未安装')"
    echo "  ROCm: $ROCM_VER"
    echo "  GPU 类型: $GPU_TYPE"
    echo "=========================================="

    # 生成 .env 文件
    cat > "$PROJECT_DIR/.env" << EOF
# AMD AI Studio 环境配置（由 check_and_install.sh 自动生成）
PYTHON_BIN=$PY_BIN
VENV_DIR=$VENV_DIR
GPU_TYPE=$GPU_TYPE
ROCM_VERSION=$ROCM_VER
PROJECT_DIR=$PROJECT_DIR
EOF
    ok "环境配置已保存: $PROJECT_DIR/.env"

    echo ""
    info "运行项目: source $VENV_DIR/bin/activate && cd $PROJECT_DIR && python app.py"
}

# ============================================================
#  Main
# ============================================================
main() {
    echo ""
    echo "=========================================="
    echo "  AMD AI Studio — 环境检测 & 依赖安装"
    echo "=========================================="
    echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=========================================="

    detect_pkg_manager
    check_hardware
    check_python_env || { err "Python 环境检测失败"; exit 1; }
    check_rocm
    check_deps

    # 安装
    if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
        echo ""
        read -rp "是否安装缺失的依赖? [Y/n]: " confirm
        confirm=${confirm:-Y}
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            install_system_deps
            install_deps
        fi
    fi

    print_summary
    echo ""
    ok "检测完成！"
}

main "$@"
