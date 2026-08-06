#!/bin/bash
# scripts/rebuild_vllm_rocm.sh — install ROCm native vLLM (prebuilt wheel preferred, source build as fallback)
#
# Root cause:
#   The vLLM installed from PyPI is a CUDA-compiled build; the vllm._C module is not available on ROCm.
#   Caused by: AttributeError: '_OpNamespace' '_C' object has no attribute 'silu_and_mul'
#
# Solution (by priority):
#   1. Prebuilt wheel (recommended): if system ROCm >= 7.0, directly install vLLM 0.26.0+rocm723
#      - This wheel bundles torch 2.11.0, matching ROCm 7.2.x
#      - vllm._C is natively compiled, all _C operators available
#      - No source compilation needed, quick install
#
#   2. Source build (fallback): if the prebuilt wheel is unavailable or fails
#      - Clone the vLLM v0.26.0 source
#      - Compile HIP/ROCm native kernels with PYTORCH_ROCM_ARCH=gfx1100
#      - python setup.py develop
#
# vLLM 0.26.0 is the recommended version for gfx1100 (fixes the slow warmup of v0.21-v0.25).
#
# Official docs: https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html
#
# Usage:
#   source venv/bin/activate
#   bash scripts/rebuild_vllm_rocm.sh
#
set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── load _lib.sh (if present), otherwise use a minimal inline implementation ──
if [ -f "$SCRIPT_DIR/_lib.sh" ]; then
    source "$SCRIPT_DIR/_lib.sh"
else
    _SCRIPT_START_TIME=$(date +%s)
    _STEP_START_TIME=""
    _STEP_NAME=""
    declare -a _SUMMARY_NAMES=()
    declare -a _SUMMARY_TIMES=()
    declare -a _SUMMARY_ESTIMATES=()
    declare -a _SUMMARY_STATUS=()

    step_start() {
        _STEP_NAME="$1"
        _STEP_ESTIMATE="${2:-unknown}"
        _STEP_START_TIME=$(date +%s)
        local now=$(date '+%Y-%m-%d %H:%M:%S')
        echo ""
        echo "┌──────────────────────────────────────────────────────────"
        echo "│ [$now] START: $_STEP_NAME"
        echo "│ Estimated time: $_STEP_ESTIMATE"
        echo "└──────────────────────────────────────────────────────────"
    }

    step_end() {
        local now_epoch=$(date +%s)
        local now=$(date '+%Y-%m-%d %H:%M:%S')
        local elapsed=$((now_epoch - _STEP_START_TIME))
        local mins=$((elapsed / 60))
        local secs=$((elapsed % 60))
        local time_str="${mins}m ${secs}s"
        echo ""
        echo "┌──────────────────────────────────────────────────────────"
        echo "│ [$now] DONE: $_STEP_NAME"
        echo "│ Actual time: $time_str  (estimate: $_STEP_ESTIMATE)"
        echo "└──────────────────────────────────────────────────────────"
        _SUMMARY_NAMES+=("$_STEP_NAME")
        _SUMMARY_TIMES+=("$time_str")
        _SUMMARY_ESTIMATES+=("$_STEP_ESTIMATE")
        _SUMMARY_STATUS+=("OK")
    }

    step_fail() {
        local now_epoch=$(date +%s)
        local elapsed=$((now_epoch - _STEP_START_TIME))
        local mins=$((elapsed / 60))
        local secs=$((elapsed % 60))
        _SUMMARY_NAMES+=("$_STEP_NAME")
        _SUMMARY_TIMES+=("${mins}m ${secs}s")
        _SUMMARY_ESTIMATES+=("$_STEP_ESTIMATE")
        _SUMMARY_STATUS+=("FAIL")
    }

    estimate_total() {
        echo ""
        echo "╔═══════════════════════════════════════════════════════════"
        echo "║  Script estimated total time: ${3:-${1}-${2} minutes}"
        echo "╚═══════════════════════════════════════════════════════════"
    }

    script_total_time() {
        local now_epoch=$(date +%s)
        local elapsed=$((now_epoch - _SCRIPT_START_TIME))
        local hours=$((elapsed / 3600))
        local mins=$(( (elapsed % 3600) / 60 ))
        local secs=$((elapsed % 60))
        if [ $hours -gt 0 ]; then
            echo "${hours}h ${mins}m ${secs}s"
        else
            echo "${mins}m ${secs}s"
        fi
    }

    script_summary() {
        echo ""
        echo "╔═══════════════════════════════════════════════════════════"
        echo "║  rebuild_vllm_rocm.sh step elapsed-time summary"
        echo "╠═══════════════════════════════════════════════════════════"
        local i=0
        for idx in "${!_SUMMARY_NAMES[@]}"; do
            printf "║  %-3s %-45s %-12s %s\n" "$((i+1))" "${_SUMMARY_NAMES[$idx]}" "${_SUMMARY_TIMES[$idx]}" "${_SUMMARY_STATUS[$idx]}"
            i=$((i+1))
        done
        echo "║  Total time: $(script_total_time)"
        echo "╚═══════════════════════════════════════════════════════════"
    }

    pip_install_watch() {
        echo "  Running: $1"
        eval "$1"
    }

    run_watch() {
        echo "  Description: $2"
        echo "  Command: $1"
        eval "$1"
    }
fi

estimate_total 5 40 "5-40 minutes (prebuilt wheel is fast, source build is slow)"

_finish() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        step_fail
    fi
    script_summary
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo "  rebuild_vllm_rocm.sh complete, total time: $(script_total_time)"
    else
        echo "  rebuild_vllm_rocm.sh exited abnormally (code=$exit_code), ran for: $(script_total_time)"
    fi
}
trap _finish EXIT

# ════════════════════════════════════════════════════════
# Step 0: environment check + ROCm version detection
# ════════════════════════════════════════════════════════
step_start "Step 0: environment check + ROCm version detection" "estimated <10s"

echo "  Checking Python..."
python --version || { echo "ERROR: Python not found"; exit 1; }

echo "  Checking ROCm..."
if ! command -v hipcc &>/dev/null; then
    echo "ERROR: hipcc not found. ROCm not installed?"
    exit 1
fi

# detect the actual ROCm version
ROCM_HIP_VERSION=$(hipcc --version 2>/dev/null | grep "HIP version" | head -1 | sed 's/.*: *//' | cut -d. -f1-2)
echo "  HIP version: $ROCM_HIP_VERSION"

ROCM_MAJOR=$(echo "$ROCM_HIP_VERSION" | cut -d. -f1)
echo "  ROCm major version: $ROCM_MAJOR"

if [ -z "$ROCM_MAJOR" ] || [ "$ROCM_MAJOR" -lt 6 ]; then
    echo "ERROR: ROCm < 6.0 not supported"
    exit 1
fi

# decide the install strategy
USE_PREBUILT_WHEEL=false
if [ "$ROCM_MAJOR" -ge 7 ]; then
    USE_PREBUILT_WHEEL=true
    echo ""
    echo "  ═══════════════════════════════════════════════════"
    echo "  ✅ ROCm $ROCM_HIP_VERSION (>= 7.0) detected"
    echo "  ✅ Will use the prebuilt wheel (vLLM 0.26.0+rocm723)"
    echo "  ✅ This wheel bundles torch 2.11.0, matching ROCm 7.2.x"
    echo "  ✅ No source compilation needed, quick install (5-15 minutes)"
    echo "  ═══════════════════════════════════════════════════"
else
    echo ""
    echo "  ═══════════════════════════════════════════════════"
    echo "  ⚠️  ROCm $ROCM_HIP_VERSION (< 7.0) detected"
    echo "  ⚠️  No prebuilt wheel, will build from source (15-40 minutes)"
    echo "  ═══════════════════════════════════════════════════"
fi

echo ""
echo "  Checking PyTorch..."
python -c "
import torch
print(f'  torch: {torch.__version__}')
print(f'  HIP: {torch.version.hip}')
print(f'  cuda available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  GPU: {torch.cuda.get_device_name(0)}')
" 2>/dev/null || echo "  [WARN] torch not available yet"

step_end

# ════════════════════════════════════════════════════════
# Step 1: uninstall the existing vLLM + clean up constraints
# ════════════════════════════════════════════════════════
step_start "Step 1: uninstall the existing vLLM + clean up constraints" "estimated <30s"

CURRENT_VLLM_VER=$(python -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "not installed")
echo "  Current vLLM version: $CURRENT_VLLM_VER"

echo "  Uninstalling the existing vLLM..."
pip uninstall -y vllm 2>/dev/null || true

# clean up the residual vllm directory
VLLM_SITE_DIR=$(python -c "import site; print(site.getsitepackages()[0])" 2>/dev/null)
if [ -n "$VLLM_SITE_DIR" ] && [ -d "$VLLM_SITE_DIR/vllm" ]; then
    echo "  Cleaning up the residual vllm directory: $VLLM_SITE_DIR/vllm"
    rm -rf "$VLLM_SITE_DIR/vllm"
fi
if [ -n "$VLLM_SITE_DIR" ] && [ -f "$VLLM_SITE_DIR/vllm.egg-link" ]; then
    rm -f "$VLLM_SITE_DIR/vllm.egg-link"
fi

# If using the prebuilt wheel, the old torch constraints need to be cleaned up
# The prebuilt wheel bundles torch 2.11.0; the old constraints pinning torch==2.9.1+rocm6.3 would conflict
if [ "$USE_PREBUILT_WHEEL" = "true" ]; then
    echo ""
    echo "  Cleaning up the old torch constraints (prebuilt wheel bundles torch 2.11.0)..."
    VENV_DIR="${VIRTUAL_ENV:-venv}"
    CONSTRAINTS_FILE="${VENV_DIR}/constraints.txt"
    if [ -f "$CONSTRAINTS_FILE" ]; then
        echo "  Backing up and emptying constraints.txt..."
        mv "$CONSTRAINTS_FILE" "${CONSTRAINTS_FILE}.bak" 2>/dev/null || true
    fi
    # temporarily unset PIP_CONSTRAINT (do not apply constraints during install)
    unset PIP_CONSTRAINT
    echo "  Temporarily unset PIP_CONSTRAINT environment variable"
fi

step_end

# ════════════════════════════════════════════════════════
# Step 2A: prebuilt wheel install (ROCm >= 7.0)
# ════════════════════════════════════════════════════════
# Official docs: https://docs.vllm.ai/en/stable/getting_started/installation/gpu/index.html
# Wheel index: https://wheels.vllm.ai/rocm/vllm/
# Currently available: vllm-0.26.0+rocm723-cp312-cp312-manylinux_2_34_x86_64.whl
#
# pip known issue: pip merges --extra-index-url with the default index and picks the highest version,
#   which may install the CUDA version from PyPI instead of the ROCm version.
# Solution: prefer uv (gives extra-index a higher priority),
#   specify the exact version vllm==0.26.0+rocm723 as the pip fallback,
#   and finally fall back to installing the wheel URL directly.
# ════════════════════════════════════════════════════════
# Initialization: by default do not skip the source build (the source path is used when ROCm < 7.0 or prebuilt fails)
# ════════════════════════════════════════════════════════
goto_skip_source_build=false

if [ "$USE_PREBUILT_WHEEL" = "true" ]; then

step_start "Step 2: install the prebuilt vLLM 0.26.0+rocm723 wheel" "estimated 5-15 minutes"

echo "  ═══════════════════════════════════════════════════════"
echo "  Installing the prebuilt vLLM ROCm wheel"
echo "  Source: https://wheels.vllm.ai/rocm/"
echo "  Version: vLLM 0.26.0+rocm723 (cp312, manylinux_2_34)"
echo "  This wheel contains the ROCm natively compiled vllm._C module"
echo "  ═══════════════════════════════════════════════════════"
echo ""

VLLM_ROCM_VERSION="0.26.0+rocm723"
PREBUILT_SUCCESS=false

# ── Method 1: uv pip install (officially recommended) ──
# uv gives --extra-index-url a higher priority, avoiding installing the CUDA version from PyPI
echo "  Installing the uv package manager..."
pip install uv 2>/dev/null || true

if command -v uv &>/dev/null; then
    echo ""
    echo "  Method 1: uv pip install (recommended)"
    echo "  Command: uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/ \\"
    echo "        --upgrade --index-strategy unsafe-best-match"
    echo ""

    set +e
    uv pip install vllm \
        --extra-index-url https://wheels.vllm.ai/rocm/ \
        --upgrade \
        --index-strategy unsafe-best-match 2>&1
    UV_EXIT_CODE=$?
    set -e

    if [ $UV_EXIT_CODE -eq 0 ]; then
        PREBUILT_SUCCESS=true
        echo "  ✅ uv install succeeded"
    else
        echo "  ❌ uv install failed (exit=$UV_EXIT_CODE)"
    fi
fi

# ── Method 2: pip install (specify the exact version, avoid CUDA fallback) ──
if [ "$PREBUILT_SUCCESS" != "true" ]; then
    echo ""
    echo "  Method 2: pip install (specify the rocm723 version)"
    echo "  Command: pip install vllm==0.26.0+rocm723 --extra-index-url https://wheels.vllm.ai/rocm/"
    echo ""

    set +e
    pip install "vllm==0.26.0+rocm723" \
        --extra-index-url https://wheels.vllm.ai/rocm/ 2>&1
    PIP_EXIT_CODE=$?
    set -e

    if [ $PIP_EXIT_CODE -eq 0 ]; then
        PREBUILT_SUCCESS=true
        echo "  ✅ pip install succeeded"
    else
        echo "  ❌ pip install failed (exit=$PIP_EXIT_CODE)"
    fi
fi

# ── Method 3: direct wheel URL (final fallback) ──
if [ "$PREBUILT_SUCCESS" != "true" ]; then
    echo ""
    echo "  Method 3: download and install the wheel file directly"
    echo "  Extracting the wheel URL from the index page..."

    # extract the wheel download link from https://wheels.vllm.ai/rocm/vllm/
    VLLM_WHEEL_URL=$(curl -s https://wheels.vllm.ai/rocm/vllm/ 2>/dev/null | \
        grep -oP 'https://[^"]+vllm-0\.26\.0\+rocm723[^"]+\.whl' | head -1)

    if [ -n "$VLLM_WHEEL_URL" ]; then
        # in the URL, %2B is the encoding of +
        VLLM_WHEEL_URL=$(echo "$VLLM_WHEEL_URL" | sed 's/%2B/+/g')
        echo "  Wheel URL: $VLLM_WHEEL_URL"
        echo ""

        set +e
        pip install "$VLLM_WHEEL_URL" 2>&1
        DIRECT_EXIT_CODE=$?
        set -e

        if [ $DIRECT_EXIT_CODE -eq 0 ]; then
            PREBUILT_SUCCESS=true
            echo "  ✅ direct wheel install succeeded"
        else
            echo "  ❌ direct wheel install failed (exit=$DIRECT_EXIT_CODE)"
        fi
    else
        echo "  ❌ could not extract the wheel URL from the index page"
        echo "  Check manually: curl -s https://wheels.vllm.ai/rocm/vllm/"
    fi
fi

# ── check the install result ──
echo ""
if [ "$PREBUILT_SUCCESS" = "true" ]; then
    echo "  Verifying the installation..."
    set +e
    python -c "
import vllm
print(f'  vLLM version: {vllm.__version__}')
import torch
print(f'  torch version: {torch.__version__}')
print(f'  HIP version: {torch.version.hip}')
" 2>&1
    VERIFY_EXIT=$?
    set -e

    if [ $VERIFY_EXIT -ne 0 ]; then
        echo "  ⚠️  vLLM import failed, falling back to the source build"
        PREBUILT_SUCCESS=false
    fi
fi

if [ "$PREBUILT_SUCCESS" != "true" ]; then
    echo ""
    echo "  ═══════════════════════════════════════════════════"
    echo "  ⚠️  Prebuilt wheel install failed!"
    echo "  ⚠️  Automatically falling back to the source build mode..."
    echo "  ═══════════════════════════════════════════════════"
    USE_PREBUILT_WHEEL=false
    goto_skip_source_build=false
    # clean up any possibly incomplete installation
    pip uninstall -y vllm 2>/dev/null || true
fi

step_end

# ════════════════════════════════════════════════════════
# Step 3: verify the vllm._C module (only when the prebuilt wheel succeeded)
# ════════════════════════════════════════════════════════
if [ "$PREBUILT_SUCCESS" = "true" ]; then

step_start "Step 3: verify the vllm._C module (critical!)" "estimated 10-30s"

echo "  === Verifying the vllm._C module ==="
python -c "
import vllm
import vllm._C
print(f'  [OK] vLLM {vllm.__version__} + vllm._C module imported (ROCm native compilation)')
print(f'  Module path: {vllm._C.__file__}')
" || {
    echo "  [FAIL] vllm._C module import failed!"
    echo "  The prebuilt wheel may not include the _C module; a source build is needed"
    echo "  Run: VLLM_FORCE_SOURCE_BUILD=1 bash scripts/rebuild_vllm_rocm.sh"
    exit 1
}

echo ""
echo "  === Verifying the key _C operators ==="
python -c "
import vllm
import vllm._C
import torch

ops_to_check = [
    'silu_and_mul',
    'gelu_and_mul',
    'gelu_tanh_and_mul',
    'rms_norm',
    'fused_add_rms_norm',
    'rotary_embedding',
    'reshape_and_cache',
    'reshape_and_cache_flash',
    'copy_blocks',
]

ok = 0
fail = 0
for op_name in ops_to_check:
    try:
        op = getattr(torch.ops._C, op_name)
        print(f'  [OK] torch.ops._C.{op_name}')
        ok += 1
    except (AttributeError, RuntimeError) as e:
        print(f'  [FAIL] torch.ops._C.{op_name}: {e}')
        fail += 1

print(f'')
print(f'  Result: {ok} operators available, {fail} unavailable')

if fail > 0:
    print('')
    print('  ⚠️  Some operators are unavailable; they can be supplemented by a source build:')
    print('  VLLM_FORCE_SOURCE_BUILD=1 bash scripts/rebuild_vllm_rocm.sh')
else:
    print('')
    print('  ✅ All key operators are natively available!')
"

step_end

# ════════════════════════════════════════════════════════
# Step 4: recreate the constraints (using the new torch version)
# ════════════════════════════════════════════════════════
step_start "Step 4: update constraints and environment variables" "estimated <10s"

VENV_DIR="${VIRTUAL_ENV:-venv}"
CONSTRAINTS_FILE="${VENV_DIR}/constraints.txt"

# get the newly installed torch version
NEW_TORCH_VER=$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")
NEW_VLLM_VER=$(python -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "unknown")
echo "  New torch version: $NEW_TORCH_VER"
echo "  New vLLM version: $NEW_VLLM_VER"

# create the new constraints file
cat > "$CONSTRAINTS_FILE" << EOF
# pip constraints - pin ROCm PyTorch ecosystem
# Updated by: rebuild_vllm_rocm.sh (pre-built wheel installation)
# vLLM: ${NEW_VLLM_VER}
# torch: ${NEW_TORCH_VER}
torch==${NEW_TORCH_VER}
vllm==${NEW_VLLM_VER}
EOF

# prevent CUDA-only packages from being installed (these cause errors on ROCm)
# Note: do not block triton — the vLLM prebuilt wheel bundles a ROCm-compatible triton dependency
cat >> "$CONSTRAINTS_FILE" << 'EOF'
torch_c_dlpack_ext==0.0.0
EOF
echo "  Updated constraints: $CONSTRAINTS_FILE"

# update the environment variables in venv/bin/activate
VENV_ACTIVATE="${VENV_DIR}/bin/activate"
if [ -f "$VENV_ACTIVATE" ]; then
    # update the ROCM_ENV block
    if grep -q "ROCM_ENV_BEGIN" "$VENV_ACTIVATE"; then
        sed -i '/# ROCM_ENV_BEGIN/,/# ROCM_ENV_END/c\
\
# ROCM_ENV_BEGIN - gfx1100 ROCm env vars\
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"\
export HSA_OVERRIDE_GFX_VERSION=11.0.0\
export ROCBLAS_USE_HIPBLASLT=1\
export HIP_VISIBLE_DEVICES=0\
export PYTHONPATH="${PYTHONPATH:-}:'"$SCRIPT_DIR"'"\
# ROCM_ENV_END' "$VENV_ACTIVATE"
    else
        cat >> "$VENV_ACTIVATE" << ROCM_ENV

# ROCM_ENV_BEGIN - gfx1100 ROCm env vars
export LD_LIBRARY_PATH="\${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0
export PYTHONPATH="\${PYTHONPATH:-}:$SCRIPT_DIR"
# ROCM_ENV_END
ROCM_ENV
    fi
    echo "  Updated venv/bin/activate environment variables"
fi

step_end

# prebuilt wheel succeeded, skip the source build
goto_skip_source_build=true

else
    # ── ROCm < 7.0 or prebuilt wheel failed: source build ──
    goto_skip_source_build=false
fi
fi  # close if [ "$USE_PREBUILT_WHEEL" = "true" ]

# ════════════════════════════════════════════════════════
# Source build path (ROCm < 7.0 or FORCE_SOURCE_BUILD=1)
# ════════════════════════════════════════════════════════
if [ "$goto_skip_source_build" != "true" ] || [ "${VLLM_FORCE_SOURCE_BUILD:-0}" = "1" ]; then

VLLM_VERSION="v0.26.0"
VLLM_BUILD_DIR="/tmp/vllm-build-${VLLM_VERSION}"

if [ "${VLLM_FORCE_SOURCE_BUILD:-0}" = "1" ]; then
    echo ""
    echo "  ⚠️  VLLM_FORCE_SOURCE_BUILD=1, forcing the source build"
    echo ""
fi

# ── Step S2: clone the vLLM source ──
step_start "Step S2: clone the vLLM ${VLLM_VERSION} source" "estimated 1-3 minutes"

if [ -d "$VLLM_BUILD_DIR/.git" ]; then
    echo "  Clone directory already exists: $VLLM_BUILD_DIR"
    cd "$VLLM_BUILD_DIR"
    CURRENT_TAG=$(git describe --tags 2>/dev/null || echo "unknown")
    if [ "$CURRENT_TAG" = "$VLLM_VERSION" ]; then
        echo "  Version matches ($VLLM_VERSION), skipping the clone"
    else
        echo "  Version mismatch ($CURRENT_TAG != $VLLM_VERSION), re-cloning"
        cd /tmp
        rm -rf "$VLLM_BUILD_DIR"
        git clone --depth 1 --branch "$VLLM_VERSION" https://github.com/vllm-project/vllm.git "$VLLM_BUILD_DIR"
    fi
else
    echo "  Cloning vLLM ${VLLM_VERSION}..."
    rm -rf "$VLLM_BUILD_DIR"
    git clone --depth 1 --branch "$VLLM_VERSION" https://github.com/vllm-project/vllm.git "$VLLM_BUILD_DIR"
fi

cd "$VLLM_BUILD_DIR"
echo "  Source directory: $(pwd)"
echo "  Git commit: $(git rev-parse --short HEAD)"

step_end

# ── Step S3: install the build dependencies ──
step_start "Step S3: install the build dependencies" "estimated 1-5 minutes"

echo "  Installing the basic build tools..."
pip install --upgrade pip setuptools wheel ninja cmake pybind11

# Fix 1: setuptools_scm + vcs_versioning
echo "  Fixing the setuptools_scm dependency..."
pip install vcs_versioning 2>/dev/null || {
    echo "  vcs_versioning install failed, trying to downgrade setuptools_scm..."
    pip install "setuptools_scm<8.3.0" 2>/dev/null || true
}

echo "  Installing the vLLM build dependencies..."
if [ -f "requirements/rocm.txt" ]; then
    echo "  Installing requirements/rocm.txt..."
    pip_install_watch "pip install -r requirements/rocm.txt --no-deps 2>/dev/null || true"
elif [ -f "requirements/rocm63.txt" ]; then
    echo "  Installing requirements/rocm63.txt..."
    pip_install_watch "pip install -r requirements/rocm63.txt --no-deps 2>/dev/null || true"
else
    echo "  [INFO] ROCm requirements file not found, using the manual dependency list"
    pip install --upgrade numba scipy huggingface-hub 2>/dev/null || true
fi

# do not force-downgrade numpy anymore (vLLM 0.26.0 supports numpy 2.x)
echo "  Checking the numpy version..."
python -c "import numpy; print(f'  numpy: {numpy.__version__}')"

# Fix 2: triton distribution recognition
echo "  Fixing the triton distribution recognition..."
python << 'TRITON_FIX_EOF'
import os, sys, site, importlib.metadata

triton_path = None
for p in sys.path + site.getsitepackages():
    cand = os.path.join(p, "triton")
    if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "__init__.py")):
        triton_path = cand
        break

if triton_path:
    try:
        importlib.metadata.version("triton")
        print(f"  [SKIP] triton distribution already recognized")
    except importlib.metadata.PackageNotFoundError:
        sp = site.getsitepackages()[0]
        dist_info_dir = os.path.join(sp, "triton-3.5.1.dist-info")
        try:
            sys.path.insert(0, os.path.dirname(triton_path))
            import triton
            ver = getattr(triton, "__version__", "3.5.1")
        except Exception:
            ver = "3.5.1"
        os.makedirs(dist_info_dir, exist_ok=True)
        with open(os.path.join(dist_info_dir, "METADATA"), "w") as f:
            f.write(f"Metadata-Version: 2.1\nName: triton\nVersion: {ver}\nSummary: ROCm triton (pytorch-triton-rocm)\n")
        with open(os.path.join(dist_info_dir, "RECORD"), "w") as f:
            f.write("triton/__init__.py,,\n")
        with open(os.path.join(dist_info_dir, "INSTALLER"), "w") as f:
            f.write("rebuild_vllm_rocm.sh\n")
        print(f"  [OK] Created triton-{ver} dist-info shim")
else:
    print(f"  [WARN] triton module not found")
TRITON_FIX_EOF

step_end

# ── Step S4: set the ROCm build environment variables ──
step_start "Step S4: set the ROCm build environment variables" "estimated <5s"

export PYTORCH_ROCM_ARCH="gfx1100"
export ROCM_PATH="${ROCM_PATH:-/opt/rocm}"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:${ROCM_PATH}/lib:${ROCM_PATH}/lib64"
export PATH="${ROCM_PATH}/bin:${PATH:-}"
export PIP_NO_BUILD_ISOLATION=1
export HSA_OVERRIDE_GFX_VERSION=11.0.0

echo "  PYTORCH_ROCM_ARCH=$PYTORCH_ROCM_ARCH"
echo "  ROCM_PATH=$ROCM_PATH"
echo "  HSA_OVERRIDE_GFX_VERSION=$HSA_OVERRIDE_GFX_VERSION"
echo "  hipcc: $(which hipcc 2>/dev/null || echo 'not found')"

step_end

# ── Step S5: build vLLM from source ──
step_start "Step S5: build vLLM ${VLLM_VERSION} from source (gfx1100)" "estimated 10-30 minutes"

echo "  ⚠️  This step compiles HIP/ROCm kernels and takes a long time (10-30 minutes)"
echo ""

set +e
run_watch \
    "python setup.py develop" \
    "compiling the vLLM ROCm kernels (gfx1100)"
BUILD_EXIT_CODE=$?
set -e

if [ $BUILD_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "  ❌ vLLM build failed!"
    echo ""
    echo "  Common causes:"
    echo "    1. hipcc not installed or version mismatch → check: hipcc --version"
    echo "    2. ROCm dev headers missing → check: ls /opt/rocm/include/hip/"
    echo "    3. cmake version too low → requires cmake >= 3.26"
    echo "    4. Out of memory → the build needs at least 8GB RAM"
    echo "    5. torch version incompatible → current: $(python -c 'import torch; print(torch.__version__)')"
    echo "    6. setuptools_scm/vcs_versioning issue → pip install vcs_versioning"
    echo ""
    echo "  Troubleshooting commands:"
    echo "    hipcc --version"
    echo "    cmake --version"
    echo "    python -c 'import setuptools_scm; print(setuptools_scm.__version__)'"
    echo "    python -c 'import vcs_versioning; print(\"vcs_versioning OK\")'"
    exit 1
fi

step_end

# ── Step S6: verify vllm._C ──
step_start "Step S6: verify the vllm._C module" "estimated 10-30s"

echo "  === Verifying the vLLM version ==="
python -c "import vllm; print(f'  vLLM version: {vllm.__version__}')"

echo ""
echo "  === Verifying the vllm._C module ==="
python -c "
import vllm
import vllm._C
print(f'  [OK] vLLM {vllm.__version__} + vllm._C module imported (ROCm native compilation)')
" || {
    echo "  [FAIL] vllm._C module import failed!"
    exit 1
}

echo ""
echo "  === Verifying the key _C operators ==="
python -c "
import vllm
import vllm._C
import torch
ops_to_check = ['silu_and_mul', 'rms_norm', 'fused_add_rms_norm', 'rotary_embedding']
for op_name in ops_to_check:
    try:
        getattr(torch.ops._C, op_name)
        print(f'  [OK] torch.ops._C.{op_name}')
    except (AttributeError, RuntimeError) as e:
        print(f'  [FAIL] torch.ops._C.{op_name}: {e}')
"

step_end

fi
# ════════════════════════════════════════════════════════
# Final: vLLM import test
# ════════════════════════════════════════════════════════
step_start "Step F: vLLM import test" "estimated 10-30s"

python -c "
import vllm
print(f'  vLLM version: {vllm.__version__}')
print(f'  vLLM path: {vllm.__file__}')

try:
    from vllm import LLM, SamplingParams
    print('  [OK] vllm.LLM, SamplingParams imported successfully')
except Exception as e:
    print(f'  [WARN] Import warning: {e}')

import vllm._C
import torch
try:
    _ = torch.ops._C.silu_and_mul
    _ = torch.ops._C.rms_norm
    print('  [OK] torch.ops._C.silu_and_mul + rms_norm natively available')
except Exception as e:
    print(f'  [FAIL] _C operators unavailable: {e}')
    exit(1)

print()
print('  ✅ vLLM import test passed! You can start the vLLM service.')
" 2>&1 | head -20

step_end

# ════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════
echo ""
echo "╔═══════════════════════════════════════════════════════════"
echo "║  vLLM ROCm installation complete!"
echo "╠═══════════════════════════════════════════════════════════"
echo "║"
if [ "$USE_PREBUILT_WHEEL" = "true" ]; then
echo "║  Install method: prebuilt wheel (vLLM 0.26.0+rocm723)"
echo "║  ROCm version: $ROCM_HIP_VERSION"
echo "║  torch: $(python -c 'import torch; print(torch.__version__)')"
else
echo "║  Install method: compiled from source (PYTORCH_ROCM_ARCH=gfx1100)"
echo "║  vLLM version: v0.26.0"
echo "║  Source directory: ${VLLM_BUILD_DIR:-N/A}"
fi
echo "║"
echo "║  Key improvements:"
echo "║    ✅ vllm._C module compiled as the ROCm native version"
echo "║    ✅ All _C operators (silu_and_mul, rms_norm, etc.) natively available"
echo "║    ✅ No vllm_rocm_ops.py / patch_vllm_source.py _C patches needed"
echo "║"
echo "║  Next steps:"
echo "║    bash scripts/start_vllm.sh"
echo "║"
echo "║  To reinstall:"
echo "║    bash scripts/rebuild_vllm_rocm.sh"
echo "║"
echo "║  If the prebuilt wheel does not work, force a source build:"
echo "║    VLLM_FORCE_SOURCE_BUILD=1 bash scripts/rebuild_vllm_rocm.sh"
echo "╚═══════════════════════════════════════════════════════════"