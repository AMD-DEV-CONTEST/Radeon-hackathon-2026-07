#!/usr/bin/env bash

set -euo pipefail

COMMAND="${1:-}"
CONFIG_FILE="${2:-}"
COMMAND_ARGUMENT="${3:-}"

if [[ -z "${COMMAND}" || -z "${CONFIG_FILE}" || ! -r "${CONFIG_FILE}" ]]; then
    echo "Usage: remote_runtime.sh <prepare-host|bootstrap|up|down|restart|status|doctor|logs|models|image-models|build-llama|switch-llama|list-llama-builds|rollback-llama|build-sd> <config-file> [argument]" >&2
    exit 2
fi

set -a
DEFAULT_CONFIG_FILE="$(dirname "${CONFIG_FILE}")/defaults.env"
if [[ -r "${DEFAULT_CONFIG_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${DEFAULT_CONFIG_FILE}"
fi
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a

required_config=(
    REMOTE_PROJECT_ROOT REMOTE_STATE_ROOT REMOTE_MODEL_ROOT REMOTE_LLAMA_SOURCE_ROOT
    REMOTE_LLAMA_RUNTIME_ROOT LLAMA_OFFICIAL_REVISION LLAMA_OFFICIAL_BUILD_NUMBER
    LLAMA_AMD_BASE_REVISION LLAMA_AMD_BASE_BUILD_NUMBER LLAMA_DEFAULT_IMPLEMENTATION
    REMOTE_STABLE_DIFFUSION_CPP_DIR STABLE_DIFFUSION_CPP_REVISION
    REMOTE_CA_BUNDLE REMOTE_REPAIR_CA_TRUST REMOTE_CA_PROBE_URL PYPI_INDEX_URL HF_ENDPOINT
    CHAT_MODEL_REPOSITORY CHAT_MODEL_REVISION
    CHAT_MODEL_FILENAME CHAT_MODEL_SHA256 CHAT_MODEL_SIZE_BYTES
    CHAT_MMPROJ_FILENAME CHAT_MMPROJ_SHA256 CHAT_MMPROJ_SIZE_BYTES
    EMBEDDING_MODEL_ID EMBEDDING_MODEL_REVISION CHAT_PROFILE_ID CHAT_SERVED_MODEL_NAME
    CHAT_NATIVE_CONTEXT_TOKENS CHAT_YARN_MAX_CONTEXT_TOKENS
    CHAT_CONTEXT_SIZE CHAT_MAX_OUTPUT_TOKENS CHAT_COMPRESSION_THRESHOLD CHAT_GPU_LAYERS
    CHAT_PARALLEL_SLOTS CHAT_ADMISSION_MAX_PENDING CHAT_ADMISSION_PER_SESSION_ACTIVE
    CHAT_ADMISSION_QUEUE_TIMEOUT_SECONDS CHAT_ADMISSION_PRIORITY_AGING_SECONDS
    CHAT_CACHE_TYPE_K CHAT_CACHE_TYPE_V EMBEDDING_PROFILE_ID
    EMBEDDING_SERVED_MODEL_NAME EMBEDDING_DIMENSIONS REMOTE_CHAT_PORT
    REMOTE_EMBEDDING_PORT REMOTE_TELEMETRY_PORT
    REMOTE_IMAGE_PORT IMAGE_PROFILE_ID IMAGE_SERVED_MODEL_NAME IMAGE_MODEL_URL
    IMAGE_MODEL_FILENAME IMAGE_MODEL_SHA256 IMAGE_MODEL_SIZE_BYTES IMAGE_VAE_URL
    IMAGE_VAE_FILENAME IMAGE_VAE_SHA256 IMAGE_VAE_SIZE_BYTES IMAGE_CLIP_L_URL
    IMAGE_CLIP_L_FILENAME IMAGE_CLIP_L_SHA256 IMAGE_CLIP_L_SIZE_BYTES IMAGE_T5XXL_URL
    IMAGE_T5XXL_FILENAME IMAGE_T5XXL_SHA256 IMAGE_T5XXL_SIZE_BYTES
    REMOTE_INFERENCE_PYTHON_PACKAGES
)
for name in "${required_config[@]}"; do
    if [[ -z "${!name:-}" ]]; then
        echo "Missing deployment setting: ${name}" >&2
        exit 2
    fi
done

numeric_config=(
    LLAMA_OFFICIAL_BUILD_NUMBER LLAMA_AMD_BASE_BUILD_NUMBER
    CHAT_MODEL_SIZE_BYTES CHAT_MMPROJ_SIZE_BYTES CHAT_NATIVE_CONTEXT_TOKENS
    CHAT_YARN_MAX_CONTEXT_TOKENS CHAT_CONTEXT_SIZE CHAT_MAX_OUTPUT_TOKENS
    CHAT_COMPRESSION_THRESHOLD CHAT_GPU_LAYERS CHAT_PARALLEL_SLOTS
    CHAT_ADMISSION_MAX_PENDING CHAT_ADMISSION_PER_SESSION_ACTIVE
    CHAT_ADMISSION_QUEUE_TIMEOUT_SECONDS CHAT_ADMISSION_PRIORITY_AGING_SECONDS
    EMBEDDING_DIMENSIONS
    REMOTE_CHAT_PORT REMOTE_EMBEDDING_PORT REMOTE_TELEMETRY_PORT
    REMOTE_IMAGE_PORT IMAGE_MODEL_SIZE_BYTES IMAGE_VAE_SIZE_BYTES IMAGE_CLIP_L_SIZE_BYTES
    IMAGE_T5XXL_SIZE_BYTES
)
for name in "${numeric_config[@]}"; do
    [[ "${!name}" =~ ^[0-9]+$ ]] || {
        echo "Deployment setting must be a non-negative integer: ${name}" >&2
        exit 2
    }
done
[[ "${REMOTE_REPAIR_CA_TRUST}" =~ ^[01]$ ]] || {
    echo "REMOTE_REPAIR_CA_TRUST must be 0 or 1" >&2
    exit 2
}
for name in REMOTE_CHAT_PORT REMOTE_EMBEDDING_PORT REMOTE_TELEMETRY_PORT REMOTE_IMAGE_PORT; do
    (( ${!name} >= 1 && ${!name} <= 65535 )) || {
        echo "Deployment port must be between 1 and 65535: ${name}" >&2
        exit 2
    }
done
[[ "${REMOTE_CHAT_PORT}" != "${REMOTE_EMBEDDING_PORT}" \
    && "${REMOTE_CHAT_PORT}" != "${REMOTE_TELEMETRY_PORT}" \
    && "${REMOTE_CHAT_PORT}" != "${REMOTE_IMAGE_PORT}" \
    && "${REMOTE_EMBEDDING_PORT}" != "${REMOTE_TELEMETRY_PORT}" \
    && "${REMOTE_EMBEDDING_PORT}" != "${REMOTE_IMAGE_PORT}" \
    && "${REMOTE_TELEMETRY_PORT}" != "${REMOTE_IMAGE_PORT}" ]] || {
    echo "Remote inference ports must be distinct" >&2
    exit 2
}

VENV_DIR="${REMOTE_STATE_ROOT}/venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
MODEL_POOL_STORE="${REMOTE_MODEL_POOL_STORE:-${REMOTE_STATE_ROOT}/model_pool/factory.sqlite}"
PID_FILE="${REMOTE_STATE_ROOT}/inference-node.pid"
LOG_FILE="${REMOTE_STATE_ROOT}/logs/inference-node.log"
EMBEDDING_PATH_FILE="${REMOTE_STATE_ROOT}/embedding-model-path"
LLAMA_OFFICIAL_SOURCE_DIR="${REMOTE_LLAMA_SOURCE_ROOT}/official"
LLAMA_AMD_SOURCE_DIR="${REMOTE_LLAMA_SOURCE_ROOT}/amd"
LLAMA_COMMON_SOURCE_DIR="${REMOTE_LLAMA_SOURCE_ROOT}/llama.cpp-common"
LLAMA_BUILDS_ROOT="${REMOTE_LLAMA_RUNTIME_ROOT}/builds"
LLAMA_ACTIVE_DIR="${REMOTE_LLAMA_RUNTIME_ROOT}/active"
LLAMA_ACTIVE_LINK="${LLAMA_ACTIVE_DIR}/llama-server"
LLAMA_ACTIVE_IMPLEMENTATION_FILE="${REMOTE_LLAMA_RUNTIME_ROOT}/active-implementation"
LLAMA_PREVIOUS_IMPLEMENTATION_FILE="${REMOTE_LLAMA_RUNTIME_ROOT}/previous-implementation"
LLAMA_SERVER_BIN="${LLAMA_ACTIVE_LINK}"
SD_SERVER_BIN="${REMOTE_STABLE_DIFFUSION_CPP_DIR}/build/bin/sd-server"
CHAT_MODEL_PATH="${REMOTE_MODEL_ROOT}/gguf/${CHAT_MODEL_FILENAME}"
CHAT_MMPROJ_PATH="${REMOTE_MODEL_ROOT}/gguf/${CHAT_MMPROJ_FILENAME}"
IMAGE_MODEL_DIR="${REMOTE_MODEL_ROOT}/image/flux1-dev-q4_0"
IMAGE_MODEL_PATH="${IMAGE_MODEL_DIR}/${IMAGE_MODEL_FILENAME}"
IMAGE_VAE_PATH="${IMAGE_MODEL_DIR}/${IMAGE_VAE_FILENAME}"
IMAGE_CLIP_L_PATH="${IMAGE_MODEL_DIR}/${IMAGE_CLIP_L_FILENAME}"
IMAGE_T5XXL_PATH="${IMAGE_MODEL_DIR}/${IMAGE_T5XXL_FILENAME}"

log() {
    printf '[remote] %s\n' "$*"
}

fail() {
    printf '[remote] ERROR: %s\n' "$*" >&2
    exit 1
}

validate_llama_implementation() {
    case "$1" in
        official|amd) ;;
        *) fail "llama.cpp implementation must be official or amd" ;;
    esac
}

llama_source_dir() {
    case "$1" in
        official) printf '%s\n' "${LLAMA_OFFICIAL_SOURCE_DIR}" ;;
        amd) printf '%s\n' "${LLAMA_AMD_SOURCE_DIR}" ;;
        *) return 2 ;;
    esac
}

validate_llama_source_tree() {
    local implementation="$1"
    local source_dir="$2"
    local required_file
    for required_file in \
        CMakeLists.txt \
        cmake/build-info.cmake \
        common/CMakeLists.txt \
        common/build-info.cpp.in \
        common/build-info.h \
        .fastagentfactory-kernel-catalog.json; do
        [[ -f "${source_dir}/${required_file}" ]] \
            || fail "Bundled ${implementation} llama.cpp source is incomplete: ${source_dir}/${required_file}"
    done
    [[ -f "${LLAMA_COMMON_SOURCE_DIR}/fastagentfactory-operator-trace.h" \
        && -f "${LLAMA_COMMON_SOURCE_DIR}/fastagentfactory-operator-trace.cpp" ]] \
        || fail "Shared llama.cpp operator trace source is incomplete: ${LLAMA_COMMON_SOURCE_DIR}"
}

llama_build_dir() {
    printf '%s/%s\n' "${LLAMA_BUILDS_ROOT}" "$1"
}

llama_binary_path() {
    local build_dir
    build_dir="$(llama_build_dir "$1")"
    printf '%s/cmake/bin/llama-server-%s\n' "${build_dir}" "$1"
}

llama_benchmark_binary_path() {
    local build_dir
    build_dir="$(llama_build_dir "$1")"
    printf '%s/cmake/bin/llama-bench-%s\n' "${build_dir}" "$1"
}

validate_llama_implementation "${LLAMA_DEFAULT_IMPLEMENTATION}"

CA_TRUST_PREPARED=0

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

run_privileged() {
    if [[ "$(id -u)" == "0" ]]; then
        "$@"
        return
    fi
    command_exists sudo \
        || fail "System package installation requires root privileges or sudo"
    sudo "$@"
}

probe_remote_tls_trust() {
    [[ -s "${REMOTE_CA_BUNDLE}" ]] || return 77
    curl \
        --silent \
        --show-error \
        --head \
        --location \
        --max-time 20 \
        --cacert "${REMOTE_CA_BUNDLE}" \
        --output /dev/null \
        "${REMOTE_CA_PROBE_URL}"
}

activate_remote_ca_environment() {
    export SSL_CERT_FILE="${REMOTE_CA_BUNDLE}"
    export REQUESTS_CA_BUNDLE="${REMOTE_CA_BUNDLE}"
    export CURL_CA_BUNDLE="${REMOTE_CA_BUNDLE}"
    export GIT_SSL_CAINFO="${REMOTE_CA_BUNDLE}"
    export PIP_CERT="${REMOTE_CA_BUNDLE}"
}

prepare_ca_trust() {
    local probe_status
    if [[ "${CA_TRUST_PREPARED}" == "1" ]]; then
        return
    fi
    if probe_remote_tls_trust; then
        log "System CA trust is ready: ${REMOTE_CA_BUNDLE}"
        activate_remote_ca_environment
        CA_TRUST_PREPARED=1
        return
    else
        probe_status=$?
    fi

    if [[ "${probe_status}" != "60" && "${probe_status}" != "77" ]]; then
        fail "TLS probe failed with curl status ${probe_status}; check DNS, routing, proxy, or firewall access to ${REMOTE_CA_PROBE_URL}"
    fi
    [[ "${REMOTE_REPAIR_CA_TRUST}" == "1" ]] \
        || fail "Remote CA trust is unavailable and REMOTE_REPAIR_CA_TRUST is disabled"
    command_exists apt-get \
        || fail "Remote CA trust is unavailable and apt-get cannot repair ca-certificates"

    log "Repairing the remote system CA trust store"
    if command_exists update-ca-certificates; then
        run_privileged update-ca-certificates --fresh
    fi
    if ! probe_remote_tls_trust; then
        export DEBIAN_FRONTEND=noninteractive
        run_privileged apt-get -o Acquire::Retries=5 update
        run_privileged apt-get -o Acquire::Retries=5 install -y --reinstall --no-install-recommends ca-certificates
        command_exists update-ca-certificates \
            || fail "ca-certificates was installed without update-ca-certificates"
        run_privileged update-ca-certificates --fresh
    fi
    probe_remote_tls_trust \
        || fail "Remote CA trust repair completed, but TLS verification still fails for ${REMOTE_CA_PROBE_URL}"
    activate_remote_ca_environment
    CA_TRUST_PREPARED=1
    log "System CA trust repair completed"
}

prepare_host() {
    local missing=()
    local command_name
    for command_name in curl cmake ninja g++ python3 rsync sha256sum; do
        command_exists "${command_name}" || missing+=("${command_name}")
    done
    if command_exists python3 && ! python3 -m venv --help >/dev/null 2>&1; then
        missing+=("python3-venv")
    fi
    if command_exists curl; then
        prepare_ca_trust
    fi
    if (( ${#missing[@]} > 0 )); then
        [[ "${REMOTE_INSTALL_BUILD_TOOLS:-1}" == "1" ]] \
            || fail "Missing build commands: ${missing[*]}. Set REMOTE_INSTALL_BUILD_TOOLS=1 or install them manually."
        command_exists apt-get || fail "Missing build commands and apt-get is unavailable: ${missing[*]}"
        log "Installing ordinary build tools only; ROCm, GPU drivers and PyTorch will not be changed"
        export DEBIAN_FRONTEND=noninteractive
        run_privileged apt-get -o Acquire::Retries=5 update
        run_privileged apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
            build-essential ca-certificates cmake curl ninja-build python3-pip python3-venv rsync
    fi
    prepare_ca_trust
    mkdir -p \
        "${REMOTE_PROJECT_ROOT}" \
        "${REMOTE_STATE_ROOT}/logs" \
        "${REMOTE_STATE_ROOT}/model_pool" \
        "${REMOTE_MODEL_ROOT}/gguf" \
        "${REMOTE_MODEL_ROOT}/modelscope" \
        "${LLAMA_OFFICIAL_SOURCE_DIR}" \
        "${LLAMA_AMD_SOURCE_DIR}" \
        "${LLAMA_BUILDS_ROOT}" \
        "${LLAMA_ACTIVE_DIR}" \
        "${IMAGE_MODEL_DIR}"
}

doctor() {
    log "Host: $(hostname)"
    log "Disk"
    if ! df -h "${REMOTE_PROJECT_ROOT}" "${REMOTE_MODEL_ROOT}" 2>/dev/null \
        | awk 'NR == 1 || !seen[$1]++'; then
        df -h /
    fi
    log "ROCm GPU"
    if command_exists rocminfo; then
        rocminfo 2>/dev/null | grep -E 'Marketing Name|Name:' | head -n 8 || true
    else
        echo "rocminfo: not installed"
    fi
    if command_exists rocm-smi; then
        rocm-smi --showproductname --showmeminfo vram --showuse 2>/dev/null || true
    else
        echo "rocm-smi: not installed"
    fi
    log "PyTorch HIP"
    python3 - <<'PY'
try:
    import torch
    print(f"torch={torch.__version__}")
    print(f"hip={torch.version.hip}")
    print(f"gpu_available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        print(f"gpu={torch.cuda.get_device_name(0)}")
        print(f"vram_gib={props.total_memory / 1024 ** 3:.2f}")
except Exception as exc:
    print(f"torch_probe_error={type(exc).__name__}: {exc}")
PY
    log "llama.cpp"
    if [[ -x "${LLAMA_SERVER_BIN}" ]]; then
        "${LLAMA_SERVER_BIN}" --version | head -n 1
        if [[ -f "${LLAMA_ACTIVE_IMPLEMENTATION_FILE}" ]]; then
            echo "active_implementation=$(<"${LLAMA_ACTIVE_IMPLEMENTATION_FILE}")"
        fi
    else
        echo "llama-server: no active implementation"
    fi
    log "ROCm profiler"
    if command_exists rocprofv3; then
        rocprofv3 --version 2>&1 | head -n 1 || true
    else
        echo "rocprofv3: not installed"
    fi
    log "stable-diffusion.cpp"
    if [[ -x "${SD_SERVER_BIN}" ]]; then
        "${SD_SERVER_BIN}" --version | head -n 1 || true
    else
        echo "sd-server: not built"
    fi
}

prepare_rocm_userspace() {
    [[ -e /dev/kfd ]] \
        || fail "/dev/kfd is unavailable; use an AMD GPU host with ROCm device access"
    if command_exists rocminfo \
        && command_exists rocprofv3 \
        && { command_exists hipcc || [[ -x /opt/rocm/llvm/bin/clang++ ]]; }; then
        log "ROCm user-space runtime, compiler, and profiler are ready"
        return
    fi
    [[ "${REMOTE_INSTALL_ROCM_USERSPACE:-1}" == "1" ]] \
        || fail "ROCm user-space tools are missing and REMOTE_INSTALL_ROCM_USERSPACE is disabled"
    command_exists apt-get \
        || fail "ROCm user-space tools are missing and apt-get is unavailable"
    local packages_text="${ROCM_USERSPACE_PACKAGES:-rocminfo rocm-hip-sdk rocprofiler-sdk}"
    local packages=()
    read -r -a packages <<< "${packages_text}"
    (( ${#packages[@]} > 0 )) || fail "ROCM_USERSPACE_PACKAGES must contain at least one package"
    log "Refreshing package metadata before ROCm user-space installation"
    run_privileged apt-get -o Acquire::Retries=5 update
    local package
    for package in "${packages[@]}"; do
        apt-cache show "${package}" >/dev/null 2>&1 \
            || fail "ROCm package is unavailable from the configured repositories: ${package}"
    done
    log "Installing missing ROCm user-space inspection and HIP build packages"
    export DEBIAN_FRONTEND=noninteractive
    run_privileged apt-get -o Acquire::Retries=5 install -y --no-install-recommends "${packages[@]}"
}

verify_rocm_runtime() {
    command_exists rocminfo || fail "rocminfo is unavailable after environment preparation"
    command_exists rocprofv3 || fail "rocprofv3 is unavailable after environment preparation"
    rocminfo >/dev/null 2>&1 || fail "rocminfo cannot access the AMD GPU"
}

verify_pytorch_runtime() {
    "${PYTHON_BIN}" - <<'PY'
import torch

if not torch.version.hip:
    raise SystemExit("PyTorch is not a ROCm/HIP build")
if not torch.cuda.is_available():
    raise SystemExit("PyTorch cannot access an AMD GPU")
print(f"Verified ROCm PyTorch {torch.__version__} on {torch.cuda.get_device_name(0)}")
PY
}

python_has_pytorch_runtime() {
    local python_bin="$1"
    [[ -x "${python_bin}" ]] || return 1
    "${python_bin}" - <<'PY' >/dev/null 2>&1
import torch

raise SystemExit(0 if torch.version.hip and torch.cuda.is_available() else 1)
PY
}

attach_preinstalled_pytorch_runtime() {
    local runtime_python="${PYTORCH_RUNTIME_PYTHON:-}"
    [[ -n "${runtime_python}" ]] || return 1
    python_has_pytorch_runtime "${runtime_python}" || return 1

    local runtime_version project_version runtime_site project_site
    runtime_version="$("${runtime_python}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    project_version="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    [[ "${runtime_version}" == "${project_version}" ]] \
        || fail "Preinstalled PyTorch Python ${runtime_version} is incompatible with project Python ${project_version}"
    runtime_site="$("${runtime_python}" -c 'import site; print(site.getsitepackages()[0])')"
    project_site="$("${PYTHON_BIN}" -c 'import site; print(site.getsitepackages()[0])')"
    [[ -d "${runtime_site}" ]] || fail "Preinstalled PyTorch site-packages is unavailable: ${runtime_site}"
    printf '%s\n' "${runtime_site}" > "${project_site}/agentfactory-rocm-runtime.pth"
    python_has_pytorch_runtime "${PYTHON_BIN}" \
        || fail "Project environment could not activate preinstalled PyTorch from ${runtime_python}"
    log "Using preinstalled ROCm PyTorch from ${runtime_python}"
}

prepare_pytorch_runtime() {
    if verify_pytorch_runtime >/dev/null 2>&1; then
        verify_pytorch_runtime
        return
    fi
    [[ "${REMOTE_INSTALL_PYTORCH:-1}" == "1" ]] \
        || fail "A ROCm/HIP PyTorch build is unavailable and REMOTE_INSTALL_PYTORCH is disabled"
    [[ -n "${PYTORCH_INDEX_URL:-}" ]] \
        || fail "A ROCm/HIP PyTorch build is unavailable; set PYTORCH_INDEX_URL to a wheel index compatible with this ROCm image"
    local packages_text="${PYTORCH_PACKAGES:-torch torchvision torchaudio}"
    local packages=()
    read -r -a packages <<< "${packages_text}"
    (( ${#packages[@]} > 0 )) || fail "PYTORCH_PACKAGES must contain at least torch"
    log "Installing configured ROCm PyTorch packages into the isolated inference environment"
    "${PYTHON_BIN}" -m pip install --index-url "${PYPI_INDEX_URL}" --upgrade pip
    "${PYTHON_BIN}" -m pip install --index-url "${PYTORCH_INDEX_URL}" --upgrade "${packages[@]}"
    verify_pytorch_runtime
}

prepare_python() {
    prepare_ca_trust
    [[ -f "${REMOTE_PROJECT_ROOT}/agent_factory/local_inference/node_server.py" ]] \
        || fail "Inference runtime is not synchronized to ${REMOTE_PROJECT_ROOT}"
    [[ -f "${REMOTE_PROJECT_ROOT}/deploy/configure_model_pool.py" ]] \
        || fail "Inference model-pool configurator is not synchronized to ${REMOTE_PROJECT_ROOT}"
    if [[ ! -x "${PYTHON_BIN}" ]]; then
        log "Creating ROCm-compatible Python environment with system site packages"
        python3 -m venv --system-site-packages "${VENV_DIR}"
    fi
    local project_site
    project_site="$("${PYTHON_BIN}" -c 'import site; print(site.getsitepackages()[0])')"
    printf '%s\n' "${REMOTE_PROJECT_ROOT}" > "${project_site}/agentfactory-inference-runtime.pth"
    attach_preinstalled_pytorch_runtime || true
    prepare_pytorch_runtime
    local source_digest dependency_digest
    source_digest="$(
        find "${REMOTE_PROJECT_ROOT}" -type f -name '*.py' -print0 \
            | sort -z \
            | xargs -0 sha256sum \
            | sha256sum \
            | awk '{print $1}'
    )"
    dependency_digest="$(
        printf '%s\n%s\n' "${source_digest}" "${REMOTE_INFERENCE_PYTHON_PACKAGES}" \
            | sha256sum \
            | awk '{print $1}'
    )"
    local marker="${REMOTE_STATE_ROOT}/python-dependencies.sha256"
    if [[ -f "${marker}" ]] \
        && [[ "$(<"${marker}")" == "${dependency_digest}" ]] \
        && "${PYTHON_BIN}" -c 'import fastapi, modelscope, sentence_transformers, torch; assert torch.version.hip' >/dev/null 2>&1; then
        log "Python dependencies are ready"
        return
    fi
    local inference_packages=()
    read -r -a inference_packages <<< "${REMOTE_INFERENCE_PYTHON_PACKAGES}"
    (( ${#inference_packages[@]} > 0 )) || fail "REMOTE_INFERENCE_PYTHON_PACKAGES must not be empty"
    log "Installing minimal inference-node dependencies without installing the Factory application"
    "${PYTHON_BIN}" -m pip install --index-url "${PYPI_INDEX_URL}" --upgrade pip
    "${PYTHON_BIN}" -m pip install \
        --index-url "${PYPI_INDEX_URL}" \
        --upgrade-strategy only-if-needed \
        "${inference_packages[@]}"
    verify_pytorch_runtime
    printf '%s\n' "${dependency_digest}" > "${marker}"
}

llama_source_digest() {
    local source_dir="$1"
    find "${source_dir}" "${LLAMA_COMMON_SOURCE_DIR}" \
        -path '*/.git' -prune -o \
        -type d -name 'build*' -prune -o \
        -type f -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
}

build_llama_implementation() {
    local implementation="$1"
    validate_llama_implementation "${implementation}"
    local source_dir build_dir cmake_dir source_revision source_build_number source_digest binary binary_sha benchmark_binary benchmark_binary_sha kernel_catalog kernel_catalog_sha custom_kernels
    source_dir="$(llama_source_dir "${implementation}")"
    build_dir="$(llama_build_dir "${implementation}")"
    cmake_dir="${build_dir}/cmake"
    binary="$(llama_binary_path "${implementation}")"
    benchmark_binary="$(llama_benchmark_binary_path "${implementation}")"
    kernel_catalog="${build_dir}/kernel-catalog.json"
    validate_llama_source_tree "${implementation}" "${source_dir}"
    if [[ "${implementation}" == "official" ]]; then
        source_revision="${LLAMA_OFFICIAL_REVISION}"
        source_build_number="${LLAMA_OFFICIAL_BUILD_NUMBER}"
        custom_kernels=false
    else
        source_revision="${LLAMA_AMD_BASE_REVISION}"
        source_build_number="${LLAMA_AMD_BASE_BUILD_NUMBER}"
        custom_kernels=true
    fi
    log "Configuring ${implementation} llama.cpp with GGML_HIP=ON"
    cmake \
        -S "${source_dir}" \
        -B "${cmake_dir}" \
        -G Ninja \
        -DGGML_HIP=ON \
        -DGGML_NATIVE=ON \
        -DLLAMA_CURL=OFF \
        -DLLAMA_BUILD_UI=OFF \
        -DLLAMA_USE_PREBUILT_UI=OFF \
        -DLLAMA_BUILD_COMMIT="${source_revision}" \
        -DLLAMA_BUILD_NUMBER="${source_build_number}" \
        -DCMAKE_BUILD_TYPE=Release
    log "Building ${implementation} llama-server and llama-bench"
    cmake --build "${cmake_dir}" --target llama-server llama-bench --parallel "$(nproc)"
    [[ -x "${cmake_dir}/bin/llama-server" ]] \
        || fail "llama-server build did not produce ${cmake_dir}/bin/llama-server"
    cp -f "${cmake_dir}/bin/llama-server" "${binary}"
    [[ -x "${cmake_dir}/bin/llama-bench" ]] \
        || fail "llama-bench build did not produce ${cmake_dir}/bin/llama-bench"
    cp -f "${cmake_dir}/bin/llama-bench" "${benchmark_binary}"
    chmod 755 "${binary}"
    chmod 755 "${benchmark_binary}"
    source_digest="$(llama_source_digest "${source_dir}")"
    binary_sha="$(sha256sum "${binary}" | awk '{print $1}')"
    benchmark_binary_sha="$(sha256sum "${benchmark_binary}" | awk '{print $1}')"
    python3 - \
        "${REMOTE_PROJECT_ROOT}/deploy/kernel-catalogs/llama-cpp-rocm-base.json" \
        "${source_dir}/.fastagentfactory-kernel-catalog.json" \
        "${kernel_catalog}" \
        "${implementation}" <<'PY'
import json
import pathlib
import sys

base_path = pathlib.Path(sys.argv[1])
overlay_path = pathlib.Path(sys.argv[2])
output_path = pathlib.Path(sys.argv[3])
implementation = sys.argv[4]
base = json.loads(base_path.read_text(encoding="utf-8"))
overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
if base.get("schema_version") != 1 or overlay.get("schema_version") != 1:
    raise SystemExit("kernel catalog schema_version must be 1")
if overlay.get("implementation") != implementation:
    raise SystemExit("kernel catalog overlay implementation does not match the build")
kernels = [*base.get("kernels", []), *overlay.get("kernels", [])]
kernel_ids = [item.get("kernel_id") for item in kernels]
if len(kernel_ids) != len(set(kernel_ids)):
    raise SystemExit("kernel catalog contains duplicate kernel_id values")
payload = {
    "schema_version": 1,
    "implementation": implementation,
    "kernels": kernels,
}
output_path.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY
    kernel_catalog_sha="$(sha256sum "${kernel_catalog}" | awk '{print $1}')"
    python3 - "${build_dir}/manifest.json" "${implementation}" "${source_revision}" \
        "${source_build_number}" "${source_digest}" "${binary}" "${binary_sha}" \
        "${benchmark_binary}" "${benchmark_binary_sha}" "${kernel_catalog}" \
        "${kernel_catalog_sha}" "${custom_kernels}" <<'PY'
import datetime
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
implementation = sys.argv[2]
payload = {
    "implementation": implementation,
    "display_name": "Official llama.cpp" if implementation == "official" else "AMD llama.cpp",
    "source_revision": sys.argv[3],
    "source_build_number": int(sys.argv[4]),
    "source_sha256": sys.argv[5],
    "binary_path": sys.argv[6],
    "binary_sha256": sys.argv[7],
    "benchmark_binary_path": sys.argv[8],
    "benchmark_binary_sha256": sys.argv[9],
    "kernel_catalog_path": sys.argv[10],
    "kernel_catalog_sha256": sys.argv[11],
    "custom_kernels": sys.argv[12].lower() == "true",
    "optimization_status": "baseline" if implementation == "official" else "experimental",
    "build_options": {
        "GGML_HIP": True,
        "GGML_NATIVE": True,
        "CMAKE_BUILD_TYPE": "Release",
        "FASTAGENTFACTORY_Q8_ACTIVATION_REUSE": implementation == "amd",
    },
    "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
    "${binary}" --version | head -n 1
    log "Built ${implementation} llama-server: ${binary}"
    log "Built ${implementation} llama-bench: ${benchmark_binary}"
}

build_llama() {
    local implementation="${1:-all}"
    case "${implementation}" in
        all)
            build_llama_implementation official
            build_llama_implementation amd
            ;;
        official|amd) build_llama_implementation "${implementation}" ;;
        *) fail "build-llama argument must be official, amd, or all" ;;
    esac
}

activate_llama_implementation() {
    local implementation="$1"
    local record_previous="${2:-1}"
    validate_llama_implementation "${implementation}"
    local binary current temporary_link
    binary="$(llama_binary_path "${implementation}")"
    [[ -x "${binary}" ]] || fail "${implementation} llama-server is not built: ${binary}"
    current=""
    [[ -f "${LLAMA_ACTIVE_IMPLEMENTATION_FILE}" ]] \
        && current="$(<"${LLAMA_ACTIVE_IMPLEMENTATION_FILE}")"
    if [[ "${record_previous}" == "1" && -n "${current}" && "${current}" != "${implementation}" ]]; then
        printf '%s\n' "${current}" > "${LLAMA_PREVIOUS_IMPLEMENTATION_FILE}"
    fi
    temporary_link="${LLAMA_ACTIVE_DIR}/.llama-server.$$.tmp"
    ln -s "${binary}" "${temporary_link}"
    mv -Tf "${temporary_link}" "${LLAMA_ACTIVE_LINK}"
    printf '%s\n' "${implementation}" > "${LLAMA_ACTIVE_IMPLEMENTATION_FILE}"
    log "Active llama.cpp implementation: ${implementation}"
}

list_llama_builds() {
    python3 - "${LLAMA_BUILDS_ROOT}" "${LLAMA_ACTIVE_IMPLEMENTATION_FILE}" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
active_file = pathlib.Path(sys.argv[2])
active = active_file.read_text(encoding="utf-8").strip() if active_file.is_file() else ""
builds = []
for implementation in ("official", "amd"):
    manifest_path = root / implementation / "manifest.json"
    if not manifest_path.is_file():
        builds.append({"implementation": implementation, "built": False, "active": implementation == active})
        continue
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.update({"built": True, "active": implementation == active})
    builds.append(payload)
print(json.dumps({"active": active, "builds": builds}, ensure_ascii=False, indent=2))
PY
}

validate_stable_diffusion_source() {
    local source_dir="$1"
    local required_file actual_revision
    for required_file in \
        CMakeLists.txt \
        ggml/CMakeLists.txt \
        thirdparty/libwebm/build/cxx_flags.cmake \
        thirdparty/libwebm/build/msvc_runtime.cmake \
        thirdparty/libwebm/build/x86-mingw-gcc.cmake \
        thirdparty/libwebm/build/x86_64-mingw-gcc.cmake \
        .fastagentfactory-revision; do
        [[ -f "${source_dir}/${required_file}" ]] \
            || fail "stable-diffusion.cpp source is incomplete: ${source_dir}/${required_file}"
    done
    actual_revision="$(tr -d '\r\n' <"${source_dir}/.fastagentfactory-revision")"
    [[ "${actual_revision}" == "${STABLE_DIFFUSION_CPP_REVISION}" ]] \
        || fail "stable-diffusion.cpp source revision does not match STABLE_DIFFUSION_CPP_REVISION"
}

build_sd() {
    validate_stable_diffusion_source "${REMOTE_STABLE_DIFFUSION_CPP_DIR}"
    local gfx_name c_compiler cxx_compiler
    gfx_name="$(rocminfo 2>/dev/null | awk '/Name: *gfx[0-9]/ && !found {value=$2; found=1} END {print value}')"
    [[ -n "${gfx_name}" ]] || fail "Unable to detect AMD GPU target from rocminfo"
    c_compiler="$(command -v clang || true)"
    cxx_compiler="$(command -v clang++ || true)"
    [[ -n "${c_compiler}" && -n "${cxx_compiler}" ]] || {
        c_compiler=/opt/rocm/llvm/bin/clang
        cxx_compiler=/opt/rocm/llvm/bin/clang++
    }
    [[ -x "${c_compiler}" && -x "${cxx_compiler}" ]] \
        || fail "ROCm clang/clang++ compiler is unavailable"
    log "Configuring stable-diffusion.cpp for ${gfx_name} with HIPBLAS"
    cmake -S "${REMOTE_STABLE_DIFFUSION_CPP_DIR}" -B "${REMOTE_STABLE_DIFFUSION_CPP_DIR}/build" -G Ninja \
        -DCMAKE_C_COMPILER="${c_compiler}" -DCMAKE_CXX_COMPILER="${cxx_compiler}" \
        -DSD_HIPBLAS=ON -DCMAKE_BUILD_TYPE=Release \
        -DGPU_TARGETS="${gfx_name}" -DAMDGPU_TARGETS="${gfx_name}"
    cmake --build "${REMOTE_STABLE_DIFFUSION_CPP_DIR}/build" --target sd-server --parallel "$(nproc)"
    [[ -x "${SD_SERVER_BIN}" ]] || fail "stable-diffusion.cpp build did not produce ${SD_SERVER_BIN}"
}

download_file() {
    prepare_ca_trust
    local url="$1"
    local destination="$2"
    local checksum="$3"
    local expected_size="$4"
    local checksum_marker="${destination}.sha256"
    if [[ -f "${destination}" ]]; then
        local actual_size
        actual_size="$(stat --format='%s' "${destination}")"
        if [[ "${actual_size}" == "${expected_size}" \
            && -f "${checksum_marker}" \
            && "$(<"${checksum_marker}")" == "${checksum}" ]]; then
            log "Using verified model file: ${destination}"
            return
        fi
        if [[ "${actual_size}" == "${expected_size}" ]]; then
            if printf '%s  %s\n' "${checksum}" "${destination}" | sha256sum --check --status; then
                printf '%s\n' "${checksum}" > "${checksum_marker}"
                log "Verified existing model file: ${destination}"
                return
            fi
            log "Removing a complete file that failed checksum validation: ${destination}"
            rm -f "${destination}" "${checksum_marker}"
        elif (( actual_size > expected_size )); then
            log "Removing an oversized incomplete download: ${destination}"
            rm -f "${destination}" "${checksum_marker}"
        fi
    fi
    log "Downloading $(basename "${destination}") with resume support"
    curl \
        --fail \
        --location \
        --retry 10 \
        --retry-all-errors \
        --cacert "${REMOTE_CA_BUNDLE}" \
        --continue-at - \
        --output "${destination}" \
        "${url}"
    [[ "$(stat --format='%s' "${destination}")" == "${expected_size}" ]] \
        || fail "Downloaded file size mismatch: ${destination}"
    printf '%s  %s\n' "${checksum}" "${destination}" | sha256sum --check --status \
        || fail "Checksum mismatch: ${destination}"
    printf '%s\n' "${checksum}" > "${checksum_marker}"
}

download_models() {
    prepare_python
    local model_base_url="${HF_ENDPOINT%/}/${CHAT_MODEL_REPOSITORY}/resolve/${CHAT_MODEL_REVISION}"
    download_file \
        "${model_base_url}/${CHAT_MODEL_FILENAME}?download=true" \
        "${CHAT_MODEL_PATH}" \
        "${CHAT_MODEL_SHA256}" \
        "${CHAT_MODEL_SIZE_BYTES}"
    download_file \
        "${model_base_url}/${CHAT_MMPROJ_FILENAME}?download=true" \
        "${CHAT_MMPROJ_PATH}" \
        "${CHAT_MMPROJ_SHA256}" \
        "${CHAT_MMPROJ_SIZE_BYTES}"
    log "Downloading or reusing ModelScope embedding model: ${EMBEDDING_MODEL_ID}"
    local embedding_path
    embedding_path="$(
        AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}" \
        "${PYTHON_BIN}" -m agent_factory.model_pool.download \
            "${EMBEDDING_MODEL_ID}" \
            --revision "${EMBEDDING_MODEL_REVISION}" \
        | tail -n 1
    )"
    [[ -d "${embedding_path}" ]] || fail "Embedding download did not return a model directory: ${embedding_path}"
    printf '%s\n' "${embedding_path}" > "${EMBEDDING_PATH_FILE}"
    download_image_models
}

download_image_models() {
    download_file "${IMAGE_MODEL_URL}" "${IMAGE_MODEL_PATH}" "${IMAGE_MODEL_SHA256}" "${IMAGE_MODEL_SIZE_BYTES}"
    download_file "${IMAGE_VAE_URL}" "${IMAGE_VAE_PATH}" "${IMAGE_VAE_SHA256}" "${IMAGE_VAE_SIZE_BYTES}"
    download_file "${IMAGE_CLIP_L_URL}" "${IMAGE_CLIP_L_PATH}" "${IMAGE_CLIP_L_SHA256}" "${IMAGE_CLIP_L_SIZE_BYTES}"
    download_file "${IMAGE_T5XXL_URL}" "${IMAGE_T5XXL_PATH}" "${IMAGE_T5XXL_SHA256}" "${IMAGE_T5XXL_SIZE_BYTES}"
    "${PYTHON_BIN}" - "${IMAGE_MODEL_DIR}/image-model.json" \
        "${IMAGE_MODEL_FILENAME}" "${IMAGE_VAE_FILENAME}" "${IMAGE_CLIP_L_FILENAME}" "${IMAGE_T5XXL_FILENAME}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = {
    "format": "stable_diffusion_cpp",
    "family": "flux1",
    "display_name": "FLUX.1-dev Q4_0",
    "quantization": "Q4_0",
    "diffusion_model": sys.argv[2],
    "vae": sys.argv[3],
    "clip_l": sys.argv[4],
    "t5xxl": sys.argv[5],
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

boolean_flag() {
    local enabled="$1"
    local name="$2"
    if [[ "${enabled}" == "1" ]]; then
        printf -- '--%s' "${name}"
    else
        printf -- '--no-%s' "${name}"
    fi
}

image_profile_arguments() {
    IMAGE_PROFILE_ARGUMENTS=(
        --image-profile-id "${IMAGE_PROFILE_ID}"
        --image-served-model-name "${IMAGE_SERVED_MODEL_NAME}"
        --image-model-path "${IMAGE_MODEL_PATH}"
        --image-vae-path "${IMAGE_VAE_PATH}"
        --image-clip-l-path "${IMAGE_CLIP_L_PATH}"
        --image-t5xxl-path "${IMAGE_T5XXL_PATH}"
        --image-revision "${STABLE_DIFFUSION_CPP_REVISION:-}"
        --image-checksum "${IMAGE_MODEL_SHA256}"
        "$(boolean_flag "${IMAGE_ENABLED:-1}" image-enabled)"
        "$(boolean_flag "${IMAGE_DIFFUSION_FLASH_ATTENTION:-1}" image-diffusion-flash-attention)"
        "$(boolean_flag "${IMAGE_EAGER_LOAD:-1}" image-eager-load)"
        "$(boolean_flag "${IMAGE_CLIP_ON_CPU:-1}" image-clip-on-cpu)"
        "$(boolean_flag "${IMAGE_VAE_TILING:-1}" image-vae-tiling)"
        "$(boolean_flag "${IMAGE_OFFLOAD_TO_CPU:-0}" image-offload-to-cpu)"
        --image-default-width "${IMAGE_DEFAULT_WIDTH:-1024}"
        --image-default-height "${IMAGE_DEFAULT_HEIGHT:-1024}"
        --image-default-steps "${IMAGE_DEFAULT_STEPS:-20}"
        --image-default-cfg-scale "${IMAGE_DEFAULT_CFG_SCALE:-1.0}"
        --image-residency-policy "${IMAGE_RESIDENCY_POLICY:-coexist_if_fit}"
        --image-timeout-seconds "${IMAGE_TIMEOUT_SECONDS:-900}"
    )
}

configure_image_profile() {
    image_profile_arguments
    AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}" \
    "${PYTHON_BIN}" "${REMOTE_PROJECT_ROOT}/deploy/configure_model_pool.py" \
        --mode node \
        --only-image \
        --prune-unconfigured-models \
        --store-path "${MODEL_POOL_STORE}" \
        "${IMAGE_PROFILE_ARGUMENTS[@]}"
}

configure_profiles() {
    [[ -f "${EMBEDDING_PATH_FILE}" ]] || fail "Embedding model path is missing; run models first"
    local embedding_path
    embedding_path="$(<"${EMBEDDING_PATH_FILE}")"
    image_profile_arguments
    AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}" \
    "${PYTHON_BIN}" "${REMOTE_PROJECT_ROOT}/deploy/configure_model_pool.py" \
        --mode node \
        --prune-unconfigured-models \
        --store-path "${MODEL_POOL_STORE}" \
        --chat-profile-id "${CHAT_PROFILE_ID}" \
        --chat-served-model-name "${CHAT_SERVED_MODEL_NAME}" \
        --chat-model-path "${CHAT_MODEL_PATH}" \
        --chat-mmproj-path "${CHAT_MMPROJ_PATH}" \
        --chat-revision "${CHAT_MODEL_REVISION}" \
        --chat-checksum "${CHAT_MODEL_SHA256}" \
        --chat-native-context-tokens "${CHAT_NATIVE_CONTEXT_TOKENS}" \
        --chat-yarn-max-context-tokens "${CHAT_YARN_MAX_CONTEXT_TOKENS}" \
        --context-size "${CHAT_CONTEXT_SIZE}" \
        --max-output-tokens "${CHAT_MAX_OUTPUT_TOKENS}" \
        --compression-threshold "${CHAT_COMPRESSION_THRESHOLD}" \
        --gpu-layers "${CHAT_GPU_LAYERS}" \
        --parallel-slots "${CHAT_PARALLEL_SLOTS}" \
        --cache-type-k "${CHAT_CACHE_TYPE_K}" \
        --cache-type-v "${CHAT_CACHE_TYPE_V}" \
        "$(boolean_flag "${CHAT_FLASH_ATTENTION:-1}" flash-attention)" \
        "$(boolean_flag "${CHAT_MTP_ENABLED:-0}" chat-mtp-enabled)" \
        --chat-mtp-max-draft-tokens "${CHAT_MTP_MAX_DRAFT_TOKENS:-3}" \
        --chat-mtp-min-draft-tokens "${CHAT_MTP_MIN_DRAFT_TOKENS:-0}" \
        --chat-mtp-min-acceptance-probability "${CHAT_MTP_MIN_ACCEPTANCE_PROBABILITY:-0.0}" \
        "$(boolean_flag "${CHAT_MTP_BACKEND_SAMPLING:-1}" chat-mtp-backend-sampling)" \
        "$(boolean_flag "${CHAT_REASONING_SUPPORTED:-1}" reasoning-supported)" \
        --embedding-profile-id "${EMBEDDING_PROFILE_ID}" \
        --embedding-served-model-name "${EMBEDDING_SERVED_MODEL_NAME}" \
        --embedding-model-path "${embedding_path}" \
        --embedding-revision "${EMBEDDING_MODEL_REVISION}" \
        --embedding-dimensions "${EMBEDDING_DIMENSIONS}" \
        "$(boolean_flag "${EMBEDDING_TRUST_REMOTE_CODE:-0}" embedding-trust-remote-code)" \
        "${IMAGE_PROFILE_ARGUMENTS[@]}"
}

node_environment() {
    export AGENTFACTORY_MODEL_ROOT="${REMOTE_MODEL_ROOT}"
    export AGENTFACTORY_MODEL_POOL_STORE_PATH="${MODEL_POOL_STORE}"
    export AGENTFACTORY_LLAMA_SERVER_PATH="${LLAMA_SERVER_BIN}"
    export AGENTFACTORY_LLAMA_IMPLEMENTATION_ROOT="${REMOTE_LLAMA_RUNTIME_ROOT}"
    export AGENTFACTORY_SD_SERVER_PATH="${SD_SERVER_BIN}"
    export AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT="http://127.0.0.1:${REMOTE_CHAT_PORT}/v1"
    export AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT="http://127.0.0.1:${REMOTE_EMBEDDING_PORT}"
    export AGENTFACTORY_LOCAL_IMAGE_ENDPOINT="http://127.0.0.1:${REMOTE_IMAGE_PORT}/v1"
    export AGENTFACTORY_INFERENCE_TELEMETRY_ENDPOINT="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}"
    export CHAT_ADMISSION_MAX_PENDING
    export CHAT_ADMISSION_PER_SESSION_ACTIVE
    export CHAT_ADMISSION_QUEUE_TIMEOUT_SECONDS
    export CHAT_ADMISSION_PRIORITY_AGING_SECONDS
}

node_running() {
    [[ -f "${PID_FILE}" ]] || return 1
    local pid
    pid="$(<"${PID_FILE}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1
}

start_node() {
    prepare_python
    [[ -x "${LLAMA_SERVER_BIN}" ]] || fail "llama-server is not built"
    [[ -x "${SD_SERVER_BIN}" ]] || fail "sd-server is not built"
    [[ -f "${MODEL_POOL_STORE}" ]] || fail "Model pool is not configured"
    if node_running; then
        log "Inference node is already running with PID $(<"${PID_FILE}")"
        return
    fi
    rm -f "${PID_FILE}"
    node_environment
    log "Starting inference control node on 127.0.0.1:${REMOTE_TELEMETRY_PORT}"
    nohup "${PYTHON_BIN}" -m agent_factory.local_inference.node_server \
        --host 127.0.0.1 \
        --port "${REMOTE_TELEMETRY_PORT}" \
        >> "${LOG_FILE}" 2>&1 < /dev/null &
    printf '%s\n' "$!" > "${PID_FILE}"
}

stop_node() {
    if ! node_running; then
        rm -f "${PID_FILE}"
        log "Inference node is not running"
        return
    fi
    local pid
    pid="$(<"${PID_FILE}")"
    log "Stopping inference node PID ${pid}"
    kill "${pid}"
    local attempt
    for attempt in {1..30}; do
        kill -0 "${pid}" >/dev/null 2>&1 || break
        sleep 1
    done
    if kill -0 "${pid}" >/dev/null 2>&1; then
        kill -KILL "${pid}" >/dev/null 2>&1 || true
    fi
    rm -f "${PID_FILE}"
}

wait_ready() {
    local health_url="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}/health"
    local runtime_url="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}/runtimes"
    local attempt
    for attempt in {1..120}; do
        if ! node_running; then
            tail -n 80 "${LOG_FILE}" 2>/dev/null || true
            fail "Inference node exited during startup"
        fi
        if curl --fail --silent --max-time 3 "${health_url}" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    curl --fail --silent --max-time 3 "${health_url}" >/dev/null \
        || fail "Inference control endpoint did not become healthy"
    log "Control endpoint is healthy; waiting for enabled inference profiles"
    for attempt in {1..900}; do
        if curl --fail --silent --max-time 5 "${runtime_url}" \
            | IMAGE_ENABLED="${IMAGE_ENABLED:-1}" "${PYTHON_BIN}" -c '
import json
import os
import sys

payload = json.load(sys.stdin)
states = {item.get("kind"): item.get("phase") for item in payload.get("runtimes", [])}
required = ["chat", "embedding"]
if os.environ.get("IMAGE_ENABLED", "1") == "1":
    required.append("image_generation")
raise SystemExit(0 if all(states.get(kind) == "ready" for kind in required) else 1)
'; then
            log "All enabled inference profiles are ready"
            return
        fi
        sleep 1
    done
    tail -n 120 "${LOG_FILE}" 2>/dev/null || true
    fail "Chat, embedding, or image model loading did not finish within 900 seconds"
}

status() {
    if node_running; then
        log "Inference node PID $(<"${PID_FILE}") is running"
    else
        log "Inference node is stopped"
    fi
    local base_url="http://127.0.0.1:${REMOTE_TELEMETRY_PORT}"
    curl --fail --silent --show-error --max-time 10 "${base_url}/runtime/software" || true
    echo
    list_llama_builds
    curl --fail --silent --show-error --max-time 10 "${base_url}/runtime/rocm" || true
    echo
    curl --fail --silent --show-error --max-time 10 "${base_url}/runtimes" || true
    echo
}

switch_llama() {
    local implementation="$1"
    validate_llama_implementation "${implementation}"
    local current was_running=0
    current=""
    [[ -f "${LLAMA_ACTIVE_IMPLEMENTATION_FILE}" ]] \
        && current="$(<"${LLAMA_ACTIVE_IMPLEMENTATION_FILE}")"
    if [[ "${current}" == "${implementation}" ]]; then
        log "Reloading the active ${implementation} llama.cpp implementation"
    fi
    node_running && was_running=1
    if (( was_running )); then
        stop_node
    fi
    activate_llama_implementation "${implementation}"
    if (( ! was_running )); then
        return
    fi
    if (start_node && wait_ready); then
        status
        return
    fi
    log "Switch to ${implementation} failed; restoring ${current:-previous implementation}"
    stop_node
    [[ -n "${current}" ]] || fail "No previous llama.cpp implementation is available for rollback"
    activate_llama_implementation "${current}" 0
    start_node
    wait_ready
    fail "Switch to ${implementation} failed and ${current} was restored"
}

rollback_llama() {
    [[ -f "${LLAMA_PREVIOUS_IMPLEMENTATION_FILE}" ]] \
        || fail "No previous llama.cpp implementation has been recorded"
    switch_llama "$(<"${LLAMA_PREVIOUS_IMPLEMENTATION_FILE}")"
}

bootstrap() {
    prepare_host
    doctor
    prepare_rocm_userspace
    verify_rocm_runtime
    prepare_python
    build_llama all
    activate_llama_implementation "${LLAMA_DEFAULT_IMPLEMENTATION}"
    build_sd
    download_models
    configure_profiles
    stop_node
    start_node
    wait_ready
    status
}

refresh_models() {
    download_models
    configure_profiles
    if node_running; then
        stop_node
        start_node
        wait_ready
    fi
}

refresh_image_models() {
    download_image_models
    configure_image_profile
}

case "${COMMAND}" in
    prepare-host) prepare_host ;;
    bootstrap) bootstrap ;;
    up) start_node; wait_ready; status ;;
    down) stop_node ;;
    restart) stop_node; start_node; wait_ready; status ;;
    status) status ;;
    doctor) doctor ;;
    logs) tail -n 200 "${LOG_FILE}" 2>/dev/null || true ;;
    models) refresh_models ;;
    image-models) refresh_image_models ;;
    build-llama) build_llama "${COMMAND_ARGUMENT:-all}" ;;
    switch-llama)
        [[ -n "${COMMAND_ARGUMENT}" ]] || fail "switch-llama requires official or amd"
        switch_llama "${COMMAND_ARGUMENT}"
        ;;
    list-llama-builds) list_llama_builds ;;
    rollback-llama) rollback_llama ;;
    build-sd) build_sd ;;
    *) fail "Unsupported command: ${COMMAND}" ;;
esac
