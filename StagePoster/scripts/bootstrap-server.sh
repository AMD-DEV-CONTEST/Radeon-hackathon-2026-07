mkdir -p /workspace/poster-engine/scripts

cat > /workspace/poster-engine/scripts/bootstrap-server.sh <<'BASH'
#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'
umask 022

# ============================================================
# StagePoster ephemeral server bootstrap
#
# 持久化内容全部放在 /workspace：
#   - Go runtime
#   - Python 3.10 runtime
#   - Python venv
#   - Hugging Face cache
#   - Go cache
#   - ComfyUI models
#
# 可重复运行，已存在且校验通过的文件不会重新下载。
# ============================================================

WORKSPACE_ROOT="${WORKSPACE_ROOT:-/workspace}"
PROJECT_ROOT="${PROJECT_ROOT:-${WORKSPACE_ROOT}/poster-engine}"
COMFYUI_DIR="${COMFYUI_DIR:-${PROJECT_ROOT}/ComfyUI}"

RUNTIME_ROOT="${RUNTIME_ROOT:-${WORKSPACE_ROOT}/.runtime}"
CACHE_ROOT="${CACHE_ROOT:-${WORKSPACE_ROOT}/.cache}"
DOWNLOAD_ROOT="${DOWNLOAD_ROOT:-${WORKSPACE_ROOT}/.downloads}"

VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/venv}"
MODEL_ROOT="${MODEL_ROOT:-${WORKSPACE_ROOT}/models/poster}"

GO_VERSION="${GO_VERSION:-1.25.0}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10.20}"

HF_REPO="${HF_REPO:-Comfy-Org/z_image_turbo}"
HF_ENDPOINT_PRIMARY="${HF_ENDPOINT_PRIMARY:-https://hf-mirror.com}"
HF_ENDPOINT_FALLBACK="${HF_ENDPOINT_FALLBACK:-https://huggingface.co}"

GOPROXY_VALUE="${GOPROXY_VALUE:-https://goproxy.cn,direct}"
GOSUMDB_VALUE="${GOSUMDB_VALUE:-sum.golang.google.cn}"

PIP_INDEX_PRIMARY="${PIP_INDEX_PRIMARY:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_INDEX_FALLBACK="${PIP_INDEX_FALLBACK:-https://pypi.org/simple}"

DOWNLOAD_MODELS="${DOWNLOAD_MODELS:-1}"
DOWNLOAD_LORA="${DOWNLOAD_LORA:-1}"
SKIP_APT="${SKIP_APT:-0}"

ENV_FILE="${WORKSPACE_ROOT}/stageposter-env.sh"
LOG_DIR="${WORKSPACE_ROOT}/logs/bootstrap"
LOG_FILE="${LOG_DIR}/bootstrap-$(date +%Y%m%d-%H%M%S).log"

mkdir -p \
    "${RUNTIME_ROOT}" \
    "${CACHE_ROOT}" \
    "${DOWNLOAD_ROOT}" \
    "${MODEL_ROOT}" \
    "${LOG_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

trap 'echo "[ERROR] line ${LINENO}: command failed: ${BASH_COMMAND}" >&2' ERR

log() {
    printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

require_root() {
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "请使用 root 运行此脚本。"
        exit 1
    fi
}

verify_sha256() {
    local file="$1"
    local expected="$2"

    echo "${expected}  ${file}" | sha256sum -c -
}

download_http_file() {
    local output="$1"
    local expected_sha="$2"
    shift 2

    if [[ -s "${output}" ]]; then
        if verify_sha256 "${output}" "${expected_sha}" >/dev/null 2>&1; then
            log "复用已下载文件：${output}"
            return 0
        fi

        log "已有文件校验失败，重新下载：${output}"
        rm -f "${output}"
    fi

    mkdir -p "$(dirname "${output}")"

    local partial="${output}.part"
    local url

    rm -f "${partial}"

    for url in "$@"; do
        log "下载：${url}"

        if curl \
            --fail \
            --location \
            --retry 6 \
            --retry-delay 5 \
            --retry-all-errors \
            --connect-timeout 30 \
            --output "${partial}" \
            "${url}"; then

            if verify_sha256 "${partial}" "${expected_sha}"; then
                mv "${partial}" "${output}"
                return 0
            fi

            log "文件校验失败：${url}"
            rm -f "${partial}"
        else
            log "下载失败，尝试下一地址：${url}"
            rm -f "${partial}"
        fi
    done

    echo "所有下载地址均失败：${output}" >&2
    return 1
}

install_system_packages() {
    if [[ "${SKIP_APT}" == "1" ]]; then
        log "SKIP_APT=1，跳过系统软件安装"
        return
    fi

    log "安装系统工具与编译依赖"

    export DEBIAN_FRONTEND=noninteractive

    apt-get update

    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        wget \
        git \
        git-lfs \
        tmux \
        jq \
        sqlite3 \
        unzip \
        zip \
        xz-utils \
        rsync \
        aria2 \
        htop \
        lsof \
        net-tools \
        procps \
        pkg-config \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libssl-dev \
        zlib1g-dev \
        libbz2-dev \
        libreadline-dev \
        libsqlite3-dev \
        libffi-dev \
        liblzma-dev \
        libncurses-dev \
        libgdbm-dev \
        libexpat1-dev \
        tk-dev \
        uuid-dev

    git lfs install --system || true
}

install_go() {
    log "检查 Go ${GO_VERSION}"

    local machine
    local go_arch
    local go_sha

    machine="$(uname -m)"

    case "${machine}" in
        x86_64|amd64)
            go_arch="amd64"
            go_sha="2852af0cb20a13139b3448992e69b868e50ed0f8a1e5940ee1de9e19a123b613"
            ;;
        aarch64|arm64)
            go_arch="arm64"
            go_sha="05de75d6994a2783699815ee553bd5a9327d8b79991de36e38b66862782f54ae"
            ;;
        *)
            echo "暂不支持的 CPU 架构：${machine}" >&2
            exit 1
            ;;
    esac

    local go_dir="${RUNTIME_ROOT}/go-${GO_VERSION}"
    local go_tar="${DOWNLOAD_ROOT}/go${GO_VERSION}.linux-${go_arch}.tar.gz"
    local current_version=""

    if [[ -x "${go_dir}/bin/go" ]]; then
        current_version="$("${go_dir}/bin/go" version 2>/dev/null || true)"
    fi

    if [[ "${current_version}" != *"go${GO_VERSION} "* ]]; then
        download_http_file \
            "${go_tar}" \
            "${go_sha}" \
            "https://go.dev/dl/go${GO_VERSION}.linux-${go_arch}.tar.gz" \
            "https://golang.google.cn/dl/go${GO_VERSION}.linux-${go_arch}.tar.gz"

        local temp_dir
        temp_dir="$(mktemp -d "${RUNTIME_ROOT}/.go-install.XXXXXX")"

        tar -C "${temp_dir}" -xzf "${go_tar}"

        rm -rf "${go_dir}"
        mv "${temp_dir}/go" "${go_dir}"
        rm -rf "${temp_dir}"
    else
        log "Go 已存在：${current_version}"
    fi

    ln -sfn "${go_dir}/bin/go" /usr/local/bin/go
    ln -sfn "${go_dir}/bin/gofmt" /usr/local/bin/gofmt

    export PATH="${go_dir}/bin:${PATH}"

    log "Go 状态：$(go version)"
}

install_python() {
    log "检查 Python ${PYTHON_VERSION}"

    local python_dir="${RUNTIME_ROOT}/python-${PYTHON_VERSION}"
    local python_bin="${python_dir}/bin/python3.10"
    local python_tar="${DOWNLOAD_ROOT}/Python-${PYTHON_VERSION}.tar.xz"

    local python_sha="de6517421601e39a9a3bc3e1bc4c7b2f239297423ee05e282598c83ec0647505"
    local current_version=""

    if [[ -x "${python_bin}" ]]; then
        current_version="$("${python_bin}" --version 2>&1 || true)"
    fi

    if [[ "${current_version}" != "Python ${PYTHON_VERSION}" ]]; then
        download_http_file \
            "${python_tar}" \
            "${python_sha}" \
            "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz"

        local build_root="${CACHE_ROOT}/python-build"
        local source_dir="${build_root}/Python-${PYTHON_VERSION}"

        rm -rf "${source_dir}"
        mkdir -p "${build_root}"

        tar -C "${build_root}" -xf "${python_tar}"

        pushd "${source_dir}" >/dev/null

        ./configure \
            --prefix="${python_dir}" \
            --with-ensurepip=install

        make -j"$(nproc)"
        make install

        popd >/dev/null
    else
        log "Python 已存在：${current_version}"
    fi

    ln -sfn "${python_bin}" /usr/local/bin/python3.10
    ln -sfn "${python_dir}/bin/pip3.10" /usr/local/bin/pip3.10

    log "Python 状态：$("${python_bin}" --version)"
}

pip_install() {
    local python_bin="$1"
    shift

    if "${python_bin}" -m pip install \
        --index-url "${PIP_INDEX_PRIMARY}" \
        "$@"; then
        return 0
    fi

    log "首选 PyPI 镜像失败，切换官方源"

    "${python_bin}" -m pip install \
        --index-url "${PIP_INDEX_FALLBACK}" \
        "$@"
}

create_venv() {
    log "检查持久化 venv：${VENV_DIR}"

    local python_bin="${RUNTIME_ROOT}/python-${PYTHON_VERSION}/bin/python3.10"
    local recreate=0

    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        recreate=1
    elif ! "${VENV_DIR}/bin/python" -c \
        'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)' \
        >/dev/null 2>&1; then
        recreate=1
    fi

    if [[ "${recreate}" == "1" ]]; then
        log "创建或修复 Python venv"

        if [[ -d "${VENV_DIR}" ]]; then
            mv \
                "${VENV_DIR}" \
                "${VENV_DIR}.broken-$(date +%Y%m%d-%H%M%S)"
        fi

        "${python_bin}" -m venv "${VENV_DIR}"
    else
        log "复用现有 venv"
    fi

    pip_install \
        "${VENV_DIR}/bin/python" \
        --upgrade \
        pip \
        setuptools \
        wheel

    pip_install \
        "${VENV_DIR}/bin/python" \
        --upgrade \
        huggingface_hub \
        hf_xet

    log "venv Python：$("${VENV_DIR}/bin/python" --version)"
    log "HF CLI：$("${VENV_DIR}/bin/hf" version 2>/dev/null || "${VENV_DIR}/bin/hf" --version)"
}

persist_comfy_model_dir() {
    local model_type="$1"
    local target="${MODEL_ROOT}/${model_type}"
    local link="${COMFYUI_DIR}/models/${model_type}"

    mkdir -p "${target}"

    if [[ ! -d "${COMFYUI_DIR}/models" ]]; then
        log "未找到 ComfyUI models 目录，跳过链接：${COMFYUI_DIR}"
        return
    fi

    if [[ -L "${link}" ]]; then
        local existing_target
        existing_target="$(readlink -f "${link}" 2>/dev/null || true)"

        if [[ "${existing_target}" == "${target}" ]]; then
            log "模型链接已正确：${link} -> ${target}"
            return
        fi

        rm -f "${link}"
    elif [[ -d "${link}" ]]; then
        log "迁移已有模型目录到持久化位置：${model_type}"

        rsync \
            -a \
            --ignore-existing \
            "${link}/" \
            "${target}/"

        rm -rf "${link}"
    elif [[ -e "${link}" ]]; then
        mv \
            "${link}" \
            "${link}.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    ln -s "${target}" "${link}"

    log "创建模型链接：${link} -> ${target}"
}

prepare_model_directories() {
    log "创建持久化模型目录"

    mkdir -p \
        "${MODEL_ROOT}/diffusion_models" \
        "${MODEL_ROOT}/text_encoders" \
        "${MODEL_ROOT}/vae" \
        "${MODEL_ROOT}/loras"

    persist_comfy_model_dir "diffusion_models"
    persist_comfy_model_dir "text_encoders"
    persist_comfy_model_dir "vae"
    persist_comfy_model_dir "loras"
}

hf_download_model() {
    local remote_path="$1"
    local destination="$2"
    local expected_sha="$3"

    if [[ -s "${destination}" ]]; then
        if verify_sha256 "${destination}" "${expected_sha}" >/dev/null 2>&1; then
            log "模型已存在并通过校验：${destination}"
            return 0
        fi

        log "模型校验失败，将重新下载：${destination}"
        rm -f "${destination}"
    fi

    local staging_root="${DOWNLOAD_ROOT}/huggingface/z_image_turbo"
    local downloaded_file="${staging_root}/${remote_path}"
    local endpoint

    mkdir -p \
        "${staging_root}" \
        "$(dirname "${destination}")"

    for endpoint in \
        "${HF_ENDPOINT_PRIMARY}" \
        "${HF_ENDPOINT_FALLBACK}"; do

        log "下载模型：${remote_path}"
        log "Hugging Face endpoint：${endpoint}"

        if HF_HOME="${CACHE_ROOT}/huggingface" \
            HF_HUB_CACHE="${CACHE_ROOT}/huggingface/hub" \
            HF_XET_CACHE="${CACHE_ROOT}/huggingface/xet" \
            HF_ENDPOINT="${endpoint}" \
            HF_HUB_ETAG_TIMEOUT=60 \
            HF_HUB_DOWNLOAD_TIMEOUT=3600 \
            "${VENV_DIR}/bin/hf" download \
                "${HF_REPO}" \
                "${remote_path}" \
                --revision main \
                --local-dir "${staging_root}"; then

            if [[ ! -s "${downloaded_file}" ]]; then
                log "命令成功但未找到目标文件：${downloaded_file}"
                continue
            fi

            if ! verify_sha256 "${downloaded_file}" "${expected_sha}"; then
                log "模型 SHA256 校验失败：${remote_path}"
                rm -f "${downloaded_file}"
                continue
            fi

            mv "${downloaded_file}" "${destination}"

            log "模型下载完成：${destination}"
            return 0
        fi

        log "当前 Hugging Face endpoint 下载失败"
    done

    echo "模型下载失败：${remote_path}" >&2
    return 1
}

download_models() {
    if [[ "${DOWNLOAD_MODELS}" != "1" ]]; then
        log "DOWNLOAD_MODELS=${DOWNLOAD_MODELS}，跳过模型下载"
        return
    fi

    log "开始下载 Z-Image Turbo 模型"
    log "BF16 全套约 21 GB，请保持磁盘和网络稳定"

    hf_download_model \
        "split_files/diffusion_models/z_image_turbo_bf16.safetensors" \
        "${MODEL_ROOT}/diffusion_models/z_image_turbo_bf16.safetensors" \
        "2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6"

    hf_download_model \
        "split_files/text_encoders/qwen_3_4b.safetensors" \
        "${MODEL_ROOT}/text_encoders/qwen_3_4b.safetensors" \
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a"

    hf_download_model \
        "split_files/vae/ae.safetensors" \
        "${MODEL_ROOT}/vae/ae.safetensors" \
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"

    if [[ "${DOWNLOAD_LORA}" == "1" ]]; then
        hf_download_model \
            "split_files/loras/z_image_turbo_distill_patch_lora_bf16.safetensors" \
            "${MODEL_ROOT}/loras/z_image_turbo_distill_patch_lora_bf16.safetensors" \
            "340cc573d887681b89a45d850af77db43fb82dd994872be5d0a9d48649eb91c8"
    fi
}

write_environment_file() {
    log "生成持久化环境文件：${ENV_FILE}"

    local go_dir="${RUNTIME_ROOT}/go-${GO_VERSION}"
    local gopath="${WORKSPACE_ROOT}/.go"

    mkdir -p \
        "${gopath}/bin" \
        "${CACHE_ROOT}/go/build" \
        "${CACHE_ROOT}/go/pkg/mod" \
        "${CACHE_ROOT}/huggingface/hub" \
        "${CACHE_ROOT}/huggingface/xet"

    cat > "${ENV_FILE}" <<EOF
# StagePoster persistent environment
# Generated by bootstrap-server.sh

export WORKSPACE_ROOT="${WORKSPACE_ROOT}"
export PROJECT_ROOT="${PROJECT_ROOT}"
export COMFYUI_DIR="${COMFYUI_DIR}"
export MODEL_ROOT="${MODEL_ROOT}"
export VENV_DIR="${VENV_DIR}"

export GOPATH="${gopath}"
export GOCACHE="${CACHE_ROOT}/go/build"
export GOMODCACHE="${CACHE_ROOT}/go/pkg/mod"
export GOPROXY="${GOPROXY_VALUE}"
export GOSUMDB="${GOSUMDB_VALUE}"

export HF_HOME="${CACHE_ROOT}/huggingface"
export HF_HUB_CACHE="${CACHE_ROOT}/huggingface/hub"
export HF_XET_CACHE="${CACHE_ROOT}/huggingface/xet"
export HF_ENDPOINT="${HF_ENDPOINT_PRIMARY}"

export PIP_INDEX_URL="${PIP_INDEX_PRIMARY}"

export PATH="${VENV_DIR}/bin:${go_dir}/bin:${gopath}/bin:\${PATH}"

if [ "\${STAGEPOSTER_AUTO_VENV:-1}" = "1" ] && \
   [ -f "${VENV_DIR}/bin/activate" ]; then
    . "${VENV_DIR}/bin/activate"
fi
EOF

    chmod 0644 "${ENV_FILE}"

    cat > /etc/profile.d/stageposter.sh <<EOF
if [ -f "${ENV_FILE}" ]; then
    . "${ENV_FILE}"
fi
EOF

    chmod 0644 /etc/profile.d/stageposter.sh

    local bashrc="${HOME}/.bashrc"
    local source_line="[ -f \"${ENV_FILE}\" ] && . \"${ENV_FILE}\""

    touch "${bashrc}"

    if ! grep -Fq "${source_line}" "${bashrc}"; then
        printf '\n%s\n' "${source_line}" >> "${bashrc}"
    fi

    # 当前脚本立即使用这些设置
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
}

verify_installation() {
    log "执行最终检查"

    echo
    echo "================ StagePoster Bootstrap ================"
    echo "Go:"
    go version

    echo
    echo "Python runtime:"
    "${RUNTIME_ROOT}/python-${PYTHON_VERSION}/bin/python3.10" --version

    echo
    echo "Python venv:"
    "${VENV_DIR}/bin/python" --version

    echo
    echo "HF CLI:"
    "${VENV_DIR}/bin/hf" version 2>/dev/null || \
        "${VENV_DIR}/bin/hf" --version

    echo
    echo "tmux:"
    tmux -V

    echo
    echo "SQLite:"
    sqlite3 --version

    echo
    echo "Git:"
    git --version

    echo
    echo "Go proxy:"
    go env GOPROXY GOSUMDB GOPATH GOCACHE GOMODCACHE

    echo
    echo "ComfyUI model links:"

    for model_type in \
        diffusion_models \
        text_encoders \
        vae \
        loras; do

        local link="${COMFYUI_DIR}/models/${model_type}"

        if [[ -L "${link}" ]]; then
            echo "${link} -> $(readlink -f "${link}")"
        else
            echo "${link} [not linked]"
        fi
    done

    echo
    echo "Models:"

    find "${MODEL_ROOT}" \
        -maxdepth 2 \
        -type f \
        -name '*.safetensors' \
        -printf '%p  %s bytes\n' \
        | sort || true

    echo
    echo "持久化环境文件：${ENV_FILE}"
    echo "初始化日志：${LOG_FILE}"
    echo "========================================================"
}

main() {
    require_root

    log "StagePoster 服务器初始化开始"
    log "持久化根目录：${WORKSPACE_ROOT}"

    install_system_packages
    install_go
    install_python
    create_venv
    prepare_model_directories
    write_environment_file
    download_models
    verify_installation

    log "服务器初始化完成"
    log "请重启 ComfyUI，使其重新扫描模型目录"
}

main "$@"
BASH
chmod +x /workspace/poster-engine/scripts/bootstrap-server.sh

