#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 022

# ============================================================
# StagePoster 一键部署脚本
#
# 功能：从零开始部署完整 StagePoster 环境
#   1. 系统依赖
#   2. uv 包管理器
#   3. Go 1.25.0
#   4. cloudflared
#   5. ComfyUI + ROCm PyTorch
#   6. vLLM ROCm 环境
#   7. 模型文件下载（带校验）
#   8. Go Backend 编译
#   9. .env 配置生成
#   10. 启动所有服务
#   11. 健康检查
#
# 用法：
#   sudo -E bash scripts/install-all.sh
#
# 环境变量：
#   SKIP_APT=1         跳过 apt 安装
#   SKIP_COMFY_TORCH=1 跳过 ComfyUI Torch 安装
#   DOWNLOAD_MODELS=1  下载模型文件
#   INSTALL_ROCM=1     安装 ROCm 驱动（通常不需要）
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_ROOT="${PROJECT_ROOT}/backend"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    printf "${BLUE}[INFO]${NC} %s\n" "$*"
}

log_success() {
    printf "${GREEN}[OK]${NC} %s\n" "$*"
}

log_warn() {
    printf "${YELLOW}[WARN]${NC} %s\n" "$*"
}

log_error() {
    printf "${RED}[ERROR]${NC} %s\n" "$*" >&2
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        log_error "请使用 root 或 sudo 运行此脚本"
        exit 1
    fi
}

check_command() {
    if command -v "$1" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

# ============================================================
# 第 1 步：检查 ROCm
# ============================================================
check_rocm() {
    log_info "检查 ROCm 环境..."

    if ! check_command rocm-smi || ! check_command rocminfo; then
        log_warn "ROCm 未安装或不在 PATH"

        if [[ "${INSTALL_ROCM:-0}" == "1" ]]; then
            log_info "INSTALL_ROCM=1，开始安装 ROCm..."
            bash "${SCRIPT_DIR}/install-rocm.sh"
            log_warn "ROCm 安装完成，需要重启。重启后请重新运行此脚本。"
            exit 0
        else
            log_error "ROCm 未安装。请使用 AMD ROCm 镜像，或设置 INSTALL_ROCM=1"
            exit 1
        fi
    fi

    log_success "ROCm 已安装"
    rocm-smi --showproductname 2>/dev/null || true
    rocminfo | grep -m1 -E 'Name:.*gfx' || true
}

# ============================================================
# 第 2 步：系统依赖
# ============================================================
install_system_deps() {
    if [[ "${SKIP_APT:-0}" == "1" ]]; then
        log_warn "SKIP_APT=1，跳过系统依赖安装"
        return
    fi

    log_info "安装系统依赖..."

    apt-get update -qq
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        wget \
        git \
        gnupg \
        iproute2 \
        jq \
        lsof \
        procps \
        rsync \
        sqlite3 \
        unzip \
        xz-utils

    log_success "系统依赖安装完成"
}

# ============================================================
# 第 3 步：uv 包管理器
# ============================================================
install_uv() {
    log_info "检查 uv..."

    if check_command uv; then
        log_success "uv 已安装: $(uv --version)"
        return
    fi

    log_info "安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL=/usr/local/bin sh

    if check_command uv; then
        log_success "uv 安装完成: $(uv --version)"
    else
        log_error "uv 安装失败"
        exit 1
    fi
}

# ============================================================
# 第 4 步：Go 1.25.0
# ============================================================
install_go() {
    log_info "检查 Go..."

    local required_version="go1.25.0"

    if check_command go; then
        local current_version
        current_version="$(go version 2>/dev/null || echo "")"

        if [[ "$current_version" == *"$required_version"* ]]; then
            log_success "Go 已安装: $current_version"
            return
        else
            log_warn "Go 版本不符: $current_version，需要 $required_version"
        fi
    fi

    log_info "安装 Go 1.25.0..."
    bash "${SCRIPT_DIR}/install-go.sh"
    log_success "Go 安装完成: $(go version)"
}

# ============================================================
# 第 5 步：cloudflared
# ============================================================
install_cloudflared() {
    log_info "检查 cloudflared..."

    if check_command cloudflared; then
        log_success "cloudflared 已安装: $(cloudflared --version 2>&1 | head -1)"
        return
    fi

    log_info "安装 cloudflared..."
    bash "${SCRIPT_DIR}/install-cloudflared.sh"
    log_success "cloudflared 安装完成"
}

# ============================================================
# 第 6 步：ComfyUI
# ============================================================
install_comfyui() {
    log_info "检查 ComfyUI..."

    local comfy_root="${COMFY_ROOT:-${PROJECT_ROOT}/ComfyUI}"
    local comfy_venv="${COMFY_VENV:-${PROJECT_ROOT}/venv}"

    if [[ -f "${comfy_root}/main.py" ]]; then
        log_success "ComfyUI 已存在: ${comfy_root}"
    else
        log_info "克隆 ComfyUI..."
        bash "${SCRIPT_DIR}/install-comfyui.sh"
    fi

    # 安装 Python 依赖
    log_info "安装 ComfyUI Python 依赖..."
    bash "${SCRIPT_DIR}/install-comfyui.sh"

    log_success "ComfyUI 安装完成"
}

# ============================================================
# 第 7 步：vLLM
# ============================================================
install_vllm() {
    log_info "检查 vLLM..."

    local vllm_venv="${VLLM_VENV:-${PROJECT_ROOT}/.venv-vllm}"

    if [[ -x "${vllm_venv}/bin/vllm" ]]; then
        log_success "vLLM 已安装"
        return
    fi

    log_info "安装 vLLM ROCm 环境..."
    bash "${SCRIPT_DIR}/install-vllm.sh"
    log_success "vLLM 安装完成"
}

# ============================================================
# 第 8 步：模型文件
# ============================================================
download_models() {
    if [[ "${DOWNLOAD_MODELS:-1}" != "1" ]]; then
        log_warn "DOWNLOAD_MODELS=${DOWNLOAD_MODELS}，跳过模型下载"
        return
    fi

    log_info "下载模型文件（约 21 GB，请保持网络稳定）..."
    bash "${SCRIPT_DIR}/download-models.sh"
    log_success "模型下载完成"
}

# ============================================================
# 第 9 步：Go Backend 编译
# ============================================================
build_backend() {
    log_info "编译 Go Backend..."

    cd "${BACKEND_ROOT}"

    # 配置 Go 代理
    export GOPROXY="${GOPROXY:-https://goproxy.cn,direct}"
    export GOSUMDB="${GOSUMDB:-sum.golang.google.cn}"

    go mod download
    go test ./...
    go build -o poster-backend ./cmd/server

    log_success "Backend 编译完成: ${BACKEND_ROOT}/poster-backend"
}

# ============================================================
# 第 10 步：生成 .env 配置
# ============================================================
generate_env() {
    log_info "生成 .env 配置..."

    local env_file="${BACKEND_ROOT}/.env"

    if [[ -f "$env_file" ]]; then
        log_warn ".env 已存在，跳过生成"
        return
    fi

    cp "${BACKEND_ROOT}/.env.example" "$env_file"

    # 设置关键默认值
    cat >> "$env_file" <<'EOF'

# 自动生成配置
STAGEPOSTER_ROOT=/workspace/poster-engine
BACKEND_ROOT=/workspace/poster-engine/backend
COMFY_ROOT=/workspace/poster-engine/ComfyUI
COMFY_VENV=/workspace/venv
VLLM_VENV=/workspace/poster-engine/.venv-vllm

# Go 代理
GOPROXY=https://goproxy.cn,direct
GOSUMDB=sum.golang.google.cn
EOF

    log_success ".env 配置生成完成"
}

# ============================================================
# 第 11 步：创建目录结构
# ============================================================
create_directories() {
    log_info "创建目录结构..."

    mkdir -p \
        "${BACKEND_ROOT}/logs" \
        "${BACKEND_ROOT}/run" \
        "${BACKEND_ROOT}/data" \
        "${BACKEND_ROOT}/storage/jobs" \
        "${BACKEND_ROOT}/storage/assets" \
        "${BACKEND_ROOT}/storage/posters"

    log_success "目录结构创建完成"
}

# ============================================================
# 第 12 步：启动服务
# ============================================================
start_services() {
    log_info "启动所有服务..."

    bash "${SCRIPT_DIR}/start-all.sh"

    log_success "所有服务启动完成"
}

# ============================================================
# 第 13 步：健康检查
# ============================================================
health_check() {
    log_info "执行健康检查..."

    sleep 3

    local backend_ready=false
    local comfy_ready=false
    local vllm_ready=false

    # 检查 Backend
    for _ in $(seq 1 30); do
        if curl -fsS http://127.0.0.1:8080/health >/dev/null 2>&1; then
            backend_ready=true
            break
        fi
        sleep 2
    done

    # 检查 ComfyUI
    for _ in $(seq 1 30); do
        if curl -fsS http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
            comfy_ready=true
            break
        fi
        sleep 2
    done

    # 检查 vLLM
    for _ in $(seq 1 30); do
        if curl -fsS http://127.0.0.1:8001/v1/models >/dev/null 2>&1; then
            vllm_ready=true
            break
        fi
        sleep 2
    done

    echo ""
    echo "=================================================="
    echo "  StagePoster 部署健康检查"
    echo "=================================================="
    echo ""

    if $backend_ready; then
        echo -e "${GREEN}✓${NC} Backend (Go)    : http://127.0.0.1:8080"
    else
        echo -e "${RED}✗${NC} Backend (Go)    : 未就绪"
    fi

    if $comfy_ready; then
        echo -e "${GREEN}✓${NC} ComfyUI         : http://127.0.0.1:8188"
    else
        echo -e "${RED}✗${NC} ComfyUI         : 未就绪"
    fi

    if $vllm_ready; then
        echo -e "${GREEN}✓${NC} vLLM (Qwen)     : http://127.0.0.1:8001"
    else
        echo -e "${RED}✗${NC} vLLM (Qwen)     : 未就绪"
    fi

    echo ""

    if $backend_ready && $comfy_ready && $vllm_ready; then
        echo -e "${GREEN}=================================================="
        echo "  部署成功！所有服务正常运行"
        echo "==================================================${NC}"
        echo ""
        echo "下一步："
        echo "  1. 查看服务状态: ${SCRIPT_DIR}/status.sh"
        echo "  2. 启动开发隧道: ${SCRIPT_DIR}/start-dev-tunnel.sh"
        echo "  3. 执行冒烟测试: ${SCRIPT_DIR}/smoke-test.sh"
        echo ""
        return 0
    else
        echo -e "${RED}=================================================="
        echo "  部分服务未就绪，请检查日志"
        echo "==================================================${NC}"
        echo ""
        echo "日志位置："
        echo "  Backend:  ${BACKEND_ROOT}/logs/backend.log"
        echo "  ComfyUI:  ${BACKEND_ROOT}/logs/comfyui.log"
        echo "  vLLM:     ${BACKEND_ROOT}/logs/vllm.log"
        echo ""
        return 1
    fi
}

# ============================================================
# 主流程
# ============================================================
main() {
    require_root

    echo ""
    echo "=================================================="
    echo "  StagePoster 一键部署"
    echo "  Project: ${PROJECT_ROOT}"
    echo "=================================================="
    echo ""

    # 导出环境变量
    export STAGEPOSTER_ROOT="${PROJECT_ROOT}"
    export BACKEND_ROOT="${BACKEND_ROOT}"
    export COMFY_ROOT="${COMFY_ROOT:-${PROJECT_ROOT}/ComfyUI}"
    export COMFY_VENV="${COMFY_VENV:-${PROJECT_ROOT}/venv}"
    export VLLM_VENV="${VLLM_VENV:-${PROJECT_ROOT}/.venv-vllm}"

    check_rocm
    install_system_deps
    install_uv
    install_go
    install_cloudflared
    install_comfyui
    install_vllm
    create_directories
    download_models
    build_backend
    generate_env
    start_services

    if health_check; then
        echo ""
        log_success "StagePoster 一键部署完成！"
        exit 0
    else
        echo ""
        log_error "部署过程中部分服务启动失败"
        exit 1
    fi
}

main "$@"
