#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — 模型下载脚本
# 下载所需模型到本地缓存目录
# 支持 Hugging Face 和 ModelScope 源
# ============================================================

set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 配置 ----------
# 模型缓存根目录（优先使用环境变量，否则用默认路径）
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$HOME/.cache/modelscope/hub}"
MODEL_DIR="${MODEL_DIR:-$HF_HOME}"

# 下载源: huggingface | modelscope（国内用户默认使用 modelscope）
SOURCE="${SOURCE:-modelscope}"

# nocache 工具路径（防止大文件下载冲掉系统页缓存）
NOCACHE_CMD=""
if command -v nocache &>/dev/null; then
    NOCACHE_CMD="nocache"
fi

# ---------- 模型清单 ----------
# 格式: 本地名称 | 模型ID | 说明 | 预估大小
declare -A MODELS
MODELS=(
    ["sdxl-base"]="AI-ModelScope/stable-diffusion-xl-base-1.0|SDXL 文生图基础模型（7GB）|7GB"
    ["sd15"]="AI-ModelScope/stable-diffusion-v1-5|SD1.5 轻量文生图（1.5GB，省显存首选）|1.5GB"
    ["sd21"]="AI-ModelScope/stable-diffusion-v2-1|SD2.1 文生图（2GB）|2GB"
    ["sdxl-turbo"]="AI-ModelScope/sdxl-turbo|SDXL Turbo 快速生成（7GB）|7GB"
    ["sdxl-lightning"]="AI-ModelScope/SDXL-Lightning|SDXL Lightning 快速生成（3GB）|3GB"
    ["sdxl-vae-fp16"]="AI-ModelScope/sdxl-vae-fp16-fix|SDXL VAE fp16 优化版（0.3GB）|0.3GB"
    ["sd-inpaint"]="AI-ModelScope/stable-diffusion-inpainting|SD1.5 图像修复模型（1.5GB）|1.5GB"
    ["svd"]="AI-ModelScope/stable-video-diffusion-img2vid|SVD 图生视频（8GB）|8GB"
    ["lcm-lora-sdxl"]="AI-ModelScope/lcm-lora-sdxl|LCM LoRA 快速推理（0.1GB）|0.1GB"
)

# ---------- 显示帮助 ----------
show_help() {
    echo ""
    echo "用法: $0 [选项] [模型名...]"
    echo ""
    echo "选项:"
    echo "  -l, --list        列出所有可用模型"
    echo "  -s, --source      下载源 (modelscope / huggingface, 默认: modelscope)"
    echo "  -d, --dir         模型缓存目录"
    echo "  -h, --help        显示帮助"
    echo ""
    echo "模型名（可指定多个，默认全部下载）:"
    for key in "${!MODELS[@]}"; do
        IFS='|' read -r id desc size <<< "${MODELS[$key]}"
        printf "  %-20s %s (%s)\n" "$key" "$desc" "$size"
    done
    echo ""
    echo "示例:"
    echo "  $0                              # 下载所有模型"
    echo "  $0 sdxl-base sdxl-vae-fp16      # 只下载指定的模型"
    echo "  $0 -s modelscope sdxl-base      # 从 ModelScope 下载"
    echo ""
}

# ---------- 列出模型 ----------
list_models() {
    echo ""
    echo "可用模型:"
    echo "----------------------------------------"
    printf "%-20s %-60s %s\n" "名称" "模型 ID" "大小"
    echo "----------------------------------------"
    for key in "${!MODELS[@]}"; do
        IFS='|' read -r id desc size <<< "${MODELS[$key]}"
        printf "%-20s %-60s %s\n" "$key" "$id" "$size"
    done
    echo "----------------------------------------"
    echo ""
}

# ---------- 下载单个模型 ----------
download_model() {
    local name="$1"
    local model_info="${MODELS[$name]:-}"
    if [[ -z "$model_info" ]]; then
        err "未知模型: $name (用 -l 查看列表)"
        return 1
    fi

    IFS='|' read -r model_id desc size <<< "$model_info"
    info "下载 [$name] → $model_id ($desc, ~$size)"

    if [[ "$SOURCE" == "modelscope" ]]; then
        # ModelScope 下载
        $PY_BIN -m pip install modelscope --quiet --no-cache-dir 2>/dev/null || true
        local ms_path="${model_id//\//_}"
        if [[ -d "$MODELSCOPE_CACHE/$ms_path" ]]; then
            ok "[$name] 已存在: $MODELSCOPE_CACHE/$ms_path"
            return 0
        fi
        $NOCACHE_CMD $PY_BIN -c "
from modelscope.hub.snapshot_download import snapshot_download
try:
    snapshot_download('$model_id', cache_dir='$MODELSCOPE_CACHE', max_workers=1)
    print('下载完成')
except Exception as e:
    print(f'下载失败: {e}')
    exit(1)
" 2>&1
    else
        # Hugging Face 下载
        if [[ -d "$HF_HOME/hub/models--${model_id//\//--}" ]]; then
            ok "[$name] 已存在缓存中"
            return 0
        fi
        $NOCACHE_CMD $PY_BIN -c "
from huggingface_hub import snapshot_download
try:
    snapshot_download(repo_id='$model_id', local_dir_use_symlinks=False, max_workers=1)
    print('下载完成')
except Exception as e:
    print(f'下载失败: {e}')
    exit(1)
" 2>&1
    fi

    if [[ $? -eq 0 ]]; then
        ok "[$name] 下载成功！"
    else
        err "[$name] 下载失败"
        return 1
    fi
}

# ---------- 配置 Hugging Face 镜像（国内加速，自动启用）----------
configure_mirror() {
    if [[ "$SOURCE" == "modelscope" ]]; then
        return
    fi
    # 如果已设置则跳过
    if [[ -n "${HF_ENDPOINT:-}" ]]; then
        return
    fi
    # 自动使用国内镜像
    warn "使用 Hugging Face 国内镜像 (hf-mirror.com)"
    export HF_ENDPOINT=https://hf-mirror.com
    ok "已设置 HF_ENDPOINT=https://hf-mirror.com"
}

# ============================================================
#  检查磁盘空间
# ============================================================
check_disk_space() {
    local total_size=0
    for key in "${!MODELS[@]}"; do
        IFS='|' read -r id desc size <<< "${MODELS[$key]}"
        local num="${size//[^0-9]/}"
        local unit="${size//[0-9]/}"
        case "$unit" in
            GB|gb|G) total_size=$((total_size + num)) ;;
            MB|mb|M) total_size=$((total_size + num / 1024)) ;;
        esac
    done

    local avail
    avail=$(df -BG "$MODEL_DIR" 2>/dev/null | awk 'NR==2{print $4}' | sed 's/G//') || avail=0
    info "模型目录: $MODEL_DIR"
    info "模型总大小: ~${total_size}GB"
    info "磁盘可用: ${avail}GB"

    if [[ $avail -lt $((total_size + 10)) ]]; then
        warn "磁盘空间可能不足！建议释放空间或指定其他目录"
        read -rp "是否继续? [y/N]: " cont
        cont=${cont:-N}
        if [[ ! "$cont" =~ ^[Yy]$ ]]; then
            info "已取消"
            exit 0
        fi
    fi
}

# ============================================================
#  Main
# ============================================================
main() {
    # 解析参数
    TARGETS=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -l|--list) list_models; exit 0 ;;
            -s|--source) SOURCE="$2"; shift 2 ;;
            -d|--dir) MODEL_DIR="$2"; shift 2 ;;
            -h|--help) show_help; exit 0 ;;
            *) TARGETS+=("$1"); shift ;;
        esac
    done

    echo ""
    echo "==========  AMD AI Studio — 模型下载  =========="
    info "下载源: $SOURCE"
    info "缓存目录: $MODEL_DIR"
    echo ""

    # 确定 Python
    PY_BIN="${PYTHON_BIN:-python3}"
    if [[ -f /opt/venv/bin/python3 ]]; then
        PY_BIN="/opt/venv/bin/python3"
    fi

    # 安装依赖
    $PY_BIN -m pip install huggingface_hub --quiet --no-cache-dir 2>/dev/null || true

    # 配置镜像
    configure_mirror

    # 检查磁盘
    check_disk_space

    # 下载
    if [[ ${#TARGETS[@]} -eq 0 ]]; then
        # 下载全部
        for key in "${!MODELS[@]}"; do
            download_model "$key"
        done
    else
        for target in "${TARGETS[@]}"; do
            download_model "$target"
        done
    fi

    echo ""
    ok "下载任务完成！"
    echo ""
    info "模型已缓存到: $MODEL_DIR"
    info "配置位置: configs/model_paths.yaml"
}

main "$@"
