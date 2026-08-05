#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — Docker 镜像构建脚本
# 构建包含 ROCm GPU 支持的 Docker 镜像
# 用法: bash scripts/docker_build.sh [选项]
# ============================================================

set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 默认参数 ----------
IMAGE_NAME="${IMAGE_NAME:-amd-ai-studio}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
NO_CACHE="${NO_CACHE:-false}"
BUILD_ARGS=""

# ---------- 解析参数 ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--name) IMAGE_NAME="$2"; shift 2 ;;
        -t|--tag)  IMAGE_TAG="$2"; shift 2 ;;
        -f|--file) DOCKERFILE="$2"; shift 2 ;;
        --no-cache) NO_CACHE="true"; shift ;;
        --push) BUILD_ARGS="$BUILD_ARGS --push"; shift ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  -n, --name       镜像名称 (默认: amd-ai-studio)"
            echo "  -t, --tag        镜像标签 (默认: latest)"
            echo "  -f, --file       Dockerfile 路径 (默认: Dockerfile)"
            echo "  --no-cache       不使用缓存构建"
            echo "  --push           构建后推送到 registry"
            echo "  -h, --help       显示帮助"
            exit 0
            ;;
        *) err "未知参数: $1"; exit 1 ;;
    esac
done

FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

# ============================================================
#  1. 前置检查
# ============================================================
echo ""
echo "=========================================="
echo "  AMD AI Studio — Docker 镜像构建"
echo "=========================================="
info "镜像: $FULL_IMAGE"
info "Dockerfile: $DOCKERFILE"

# 检查 Docker 是否可用
if ! command -v docker &>/dev/null; then
    err "Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 Docker daemon
if ! docker info &>/dev/null; then
    err "Docker daemon 未运行，请先启动: sudo dockerd &"
    exit 1
fi

# 检查 Dockerfile
if [[ ! -f "$DOCKERFILE" ]]; then
    err "Dockerfile 不存在: $DOCKERFILE"
    exit 1
fi

# 检查 .dockerignore
if [[ ! -f .dockerignore ]]; then
    warn ".dockerignore 不存在，构建上下文可能较大"
fi

# 检查 ROCm 设备（构建时提示，不影响构建）
if [[ -c /dev/kfd ]] && ls /dev/dri/*.0 &>/dev/null 2>&1; then
    ok "检测到 ROCm 设备 (kfd + dri)"
else
    warn "未检测到 ROCm 设备，镜像仍可构建但 GPU 加速不可用"
    warn "请确保在 AMD GPU 机器上运行容器"
fi

# ============================================================
#  2. 构建镜像
# ============================================================
echo ""
echo "==========  构建 Docker 镜像  =========="

# 构建参数
BUILD_CMD="docker build"
if [[ "$NO_CACHE" == "true" ]]; then
    BUILD_CMD="$BUILD_CMD --no-cache"
    info "使用 --no-cache 模式"
fi

BUILD_CMD="$BUILD_CMD -f $DOCKERFILE -t $FULL_IMAGE ."

info "执行: $BUILD_CMD"
echo ""

# 计时
START_TIME=$(date +%s)

# 执行构建
eval "$BUILD_CMD" 2>&1

BUILD_EXIT=$?
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

if [[ $BUILD_EXIT -eq 0 ]]; then
    echo ""
    ok "构建成功！耗时: ${DURATION}秒"
    info "镜像: $FULL_IMAGE"
    info "大小: $(docker images --format '{{.Size}}' $FULL_IMAGE 2>/dev/null || echo 'N/A')"
else
    err "构建失败 (exit code: $BUILD_EXIT)"
    exit 1
fi

# ============================================================
#  3. 验证镜像
# ============================================================
echo ""
echo "==========  验证镜像  =========="

docker run --rm \
    --device=/dev/kfd --device=/dev/dri \
    --group-add=video --group-add=render \
    "$FULL_IMAGE" \
    python -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA可用: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'ROCm: {torch.version.rocm}')
    print(f'GPU: {torch.cuda.get_device_name(0)}')
" 2>&1

if [[ $? -eq 0 ]]; then
    ok "镜像验证通过！"
else
    warn "镜像验证异常（可能由于 GPU 设备未透传）"
fi

# ============================================================
#  4. 推送（可选）
# ============================================================
if [[ "$BUILD_ARGS" == *"--push"* ]]; then
    echo ""
    echo "==========  推送镜像  =========="
    docker push "$FULL_IMAGE" 2>&1 && ok "推送成功！" || err "推送失败"
fi

echo ""
echo "=========================================="
ok "构建流程完成！"
echo ""
info "启动容器:"
echo "  docker compose up -d"
echo ""
info "或手动启动:"
echo "  bash scripts/docker_start.sh"
echo "=========================================="