#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — Docker 容器启动脚本
# 启动带 ROCm GPU 透传的完整环境
# 用法: bash scripts/docker_start.sh [选项]
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
CONTAINER_NAME="${CONTAINER_NAME:-amd-ai-studio}"
PORT="${PORT:-7860}"
MODE="${MODE:-web}"  # web | headless | api | shell
MOUNT_CODE="${MOUNT_CODE:-true}"  # 是否挂载代码目录（开发模式）

# ---------- 解析参数 ----------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--name)       CONTAINER_NAME="$2"; shift 2 ;;
        -i|--image)      IMAGE_NAME="$2"; IMAGE_TAG="${3:-latest}"; shift 2 ;;
        -p|--port)       PORT="$2"; shift 2 ;;
        -m|--mode)       MODE="$2"; shift 2 ;;
        --no-mount)      MOUNT_CODE="false"; shift ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  -n, --name       容器名称 (默认: amd-ai-studio)"
            echo "  -i, --image      镜像名称:标签 (默认: amd-ai-studio:latest)"
            echo "  -p, --port       端口映射 (默认: 7860)"
            echo "  -m, --mode       启动模式: web / headless / api / shell (默认: web)"
            echo "  --no-mount       不挂载代码目录（使用镜像内代码）"
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
echo "  AMD AI Studio — Docker 容器启动"
echo "=========================================="
info "镜像: $FULL_IMAGE"
info "容器: $CONTAINER_NAME"
info "模式: $MODE"
info "端口: $PORT"

# 检查 Docker
if ! command -v docker &>/dev/null; then err "Docker 未安装"; exit 1; fi
if ! docker info &>/dev/null; then err "Docker daemon 未运行"; exit 1; fi

# 检查镜像是否存在
if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${FULL_IMAGE}$"; then
    warn "镜像 ${FULL_IMAGE} 不存在，尝试构建..."
    bash scripts/docker_build.sh -n "$IMAGE_NAME" -t "$IMAGE_TAG" || {
        err "镜像构建失败，请先手动构建: bash scripts/docker_build.sh"
        exit 1
    }
fi

# 检查是否已有同名容器运行
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    warn "容器 ${CONTAINER_NAME} 已在运行"
    info "  重启: docker restart ${CONTAINER_NAME}"
    info "  停止: docker stop ${CONTAINER_NAME}"
    info "  查看日志: docker logs -f ${CONTAINER_NAME}"
    exit 0
fi

# 清理同名已停止容器
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    info "清理已停止的容器: ${CONTAINER_NAME}"
    docker rm "$CONTAINER_NAME" >/dev/null
fi

# 检查 ROCm 设备
HAS_ROCM=false
if [[ -c /dev/kfd ]] && ls /dev/dri/*.0 &>/dev/null 2>&1; then
    HAS_ROCM=true
    ok "检测到 ROCm 设备"
else
    warn "未检测到 ROCm 设备，GPU 加速不可用"
fi

# ============================================================
#  2. 构建启动命令
# ============================================================
echo ""
echo "==========  启动容器  =========="

# 基础 Docker 参数
DOCKER_CMD="docker run -d"

# 容器名称
DOCKER_CMD="$DOCKER_CMD --name $CONTAINER_NAME"

# 重启策略
DOCKER_CMD="$DOCKER_CMD --restart unless-stopped"

# ROCm GPU 透传
if $HAS_ROCM; then
    DOCKER_CMD="$DOCKER_CMD --device=/dev/kfd --device=/dev/dri"
    DOCKER_CMD="$DOCKER_CMD --group-add=video --group-add=render"
    DOCKER_CMD="$DOCKER_CMD --security-opt seccomp=unconfined"
    DOCKER_CMD="$DOCKER_CMD --cap-add SYS_PTRACE"
fi

# 网络（使用 host 模式，方便 GPU 透传）
DOCKER_CMD="$DOCKER_CMD --network host"

# 环境变量
DOCKER_CMD="$DOCKER_CMD -e HOST=0.0.0.0"
DOCKER_CMD="$DOCKER_CMD -e PORT=$PORT"
DOCKER_CMD="$DOCKER_CMD -e SHARE=false"
DOCKER_CMD="$DOCKER_CMD -e HF_HOME=/workspace/.cache/huggingface"

# ROCm 环境变量
if $HAS_ROCM; then
    DOCKER_CMD="$DOCKER_CMD -e HSA_OVERRIDE_GFX_VERSION=11.0.0"
    DOCKER_CMD="$DOCKER_CMD -e HIP_VISIBLE_DEVICES=0"
    DOCKER_CMD="$DOCKER_CMD -e FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE"
fi

# 国内镜像（按需取消注释）
# DOCKER_CMD="$DOCKER_CMD -e HF_ENDPOINT=https://hf-mirror.com"

# 卷挂载
# 模型缓存持久化
DOCKER_CMD="$DOCKER_CMD -v amd-ai-studio-hf-cache:/workspace/.cache/huggingface"
DOCKER_CMD="$DOCKER_CMD -v amd-ai-studio-modelscope-cache:/workspace/.cache/modelscope"

# 输出目录持久化
DOCKER_CMD="$DOCKER_CMD -v amd-ai-studio-outputs:/workspace/amd-ai-studio/outputs"

# 代码目录挂载（开发模式，热重载）
if [[ "$MOUNT_CODE" == "true" ]]; then
    DOCKER_CMD="$DOCKER_CMD -v $(pwd):/workspace/amd-ai-studio"
    info "代码目录已挂载（开发模式，代码修改即时生效）"
fi

# 启动命令（根据模式）
case "$MODE" in
    web)
        DOCKER_CMD="$DOCKER_CMD $FULL_IMAGE"
        info "启动 Web UI 模式"
        ;;
    headless)
        DOCKER_CMD="$DOCKER_CMD $FULL_IMAGE bash scripts/start.sh headless"
        info "启动命令行模式"
        ;;
    api)
        DOCKER_CMD="$DOCKER_CMD $FULL_IMAGE bash scripts/start.sh api"
        info "启动 API 模式"
        ;;
    shell)
        DOCKER_CMD="$DOCKER_CMD -it $FULL_IMAGE /bin/bash"
        info "启动交互式 Shell"
        ;;
    *)
        err "未知模式: $MODE (可选: web, headless, api, shell)"
        exit 1
        ;;
esac

# ============================================================
#  3. 启动容器
# ============================================================
info "执行: docker run ... $FULL_IMAGE"
echo ""

if [[ "$MODE" == "shell" ]]; then
    # 交互式模式
    eval "${DOCKER_CMD/docker run -d/docker run -it}"
else
    # 后台模式
    eval "$DOCKER_CMD" 2>&1
    if [[ $? -eq 0 ]]; then
        ok "容器已启动: ${CONTAINER_NAME}"
        echo ""
        info "访问地址: http://localhost:${PORT}"
        info "查看日志: docker logs -f ${CONTAINER_NAME}"
        info "停止容器: docker stop ${CONTAINER_NAME}"
        info "进入容器: docker exec -it ${CONTAINER_NAME} /bin/bash"
    else
        err "容器启动失败"
        exit 1
    fi
fi

echo ""
echo "=========================================="
ok "启动完成！"
echo "=========================================="